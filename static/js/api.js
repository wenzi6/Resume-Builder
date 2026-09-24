/**
 * API 封装：统一 fetch、错误处理、JSON / blob 下载。
 */

const BASE = "";

async function request(url, options = {}) {
  const opt = { headers: {}, ...options };
  if (opt.json !== undefined) {
    opt.method = opt.method || "POST";
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(opt.json);
    delete opt.json;
  }
  let resp;
  try {
    resp = await fetch(BASE + url, opt);
  } catch (e) {
    throw new Error(`网络请求失败：${e.message}`);
  }
  if (!resp.ok) {
    let detail = "";
    try {
      const data = await resp.json();
      detail = data.error || data.message || JSON.stringify(data);
    } catch {
      detail = (await resp.text()).slice(0, 200);
    }
    throw new Error(detail || `请求失败（HTTP ${resp.status}）`);
  }
  return resp;
}

export async function getJson(url) {
  const resp = await request(url);
  return resp.json();
}

export async function postJson(url, body) {
  const resp = await request(url, { method: "POST", json: body });
  return resp.json();
}

export async function putJson(url, body) {
  const resp = await request(url, { method: "PUT", json: body });
  return resp.json();
}

export async function del(url) {
  const resp = await request(url, { method: "DELETE" });
  return resp.json();
}

/** POST 并触发浏览器下载（blob 响应），返回服务端质量警告（如有）。 */
export async function postDownload(url, body, filename) {
  let resp;
  try {
    resp = await fetch(BASE + url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new Error(`网络请求失败：${e.message}`);
  }
  if (!resp.ok) {
    let detail = "";
    try {
      const data = await resp.json();
      detail = data.error || "";
    } catch {
      /* 非 JSON 错误响应 */
    }
    throw new Error(detail || `导出失败（HTTP ${resp.status}）`);
  }
  // 服务端质量自检警告（如 PDF 字体 Type3 降级）
  const warnings = [];
  const warnHeader = resp.headers.get("X-Resume-Warnings");
  if (warnHeader) {
    try {
      warnings.push(...JSON.parse(decodeURIComponent(warnHeader)));
    } catch {
      warnings.push(decodeURIComponent(warnHeader));
    }
  }
  const blob = await resp.blob();
  const url2 = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url2;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url2), 5000);
  return warnings;
}

/** multipart 上传（导入 JSON / PDF / 模板）。 */
export async function postForm(url, formData) {
  let resp;
  try {
    resp = await fetch(BASE + url, { method: "POST", body: formData });
  } catch (e) {
    throw new Error(`网络请求失败：${e.message}`);
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.error || `请求失败（HTTP ${resp.status}）`);
  }
  return data;
}

/** 渲染预览 HTML（返回文本，非 JSON）。 */
export async function postRender(doc) {
  const resp = await request("/api/v1/render", { method: "POST", json: { document: doc } });
  return resp.text();
}

/* ---------- 具体端点 ---------- */

export const api = {
  getJson,
  postJson,
  putJson,
  del,
  schema: () => getJson("/api/v1/schema/sections"),
  templates: () => getJson("/api/v1/templates"),
  documents: () => getJson("/api/v1/documents"),
  createDocument: (templateId, title) =>
    postJson("/api/v1/documents", { templateId, title }),
  createFromSample: (name) => postJson(`/api/v1/documents/from-sample/${name}`, {}),
  getDocument: (id) => getJson(`/api/v1/documents/${id}`),
  saveDocument: (id, doc) => putJson(`/api/v1/documents/${id}`, { document: doc }),
  deleteDocument: (id) => del(`/api/v1/documents/${id}`),
  duplicateDocument: (id) => postJson(`/api/v1/documents/${id}/duplicate`, {}),
  pageInfo: (doc) => postJson("/api/v1/page-info", { document: doc }),
  autoPagebreaks: (doc) => postJson("/api/v1/auto-pagebreaks", { document: doc }),
  autoFit: (doc) => postJson("/api/v1/auto-fit", { document: doc }),
  exportPdf: (id) => postDownload("/api/v1/export/pdf", { id }, "resume.pdf"),
  exportDocx: (id) => postDownload("/api/v1/export/docx", { id }, "resume.docx"),
  exportJson: (id) => postDownload("/api/v1/export/json", { id }, "resume.json"),
  importJson: async (file) => {
    const text = await file.text();
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      throw new Error("不是有效的 JSON 文件");
    }
    return postJson("/api/v1/import/json", parsed);
  },
  importPdf: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return postForm("/api/v1/import/pdf", fd);
  },
  importTemplate: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return postForm("/api/v1/import-template", fd);
  },
};
