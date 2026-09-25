/**
 * 前端错误回传：JS 异常 / Promise 拒绝 / API 5xx 统一送到服务端日志文件。
 * 去重防刷屏，失败静默（日志链路本身不能影响使用）。
 */

const ENDPOINT = "/api/v1/logs/client";
const seen = new Map();   // 指纹 -> 时间戳
const DEDUPE_MS = 10000;

function fingerprint(msg, src) {
  return `${String(msg).slice(0, 80)}|${src || ""}`;
}

function report(kind, message, extra = {}) {
  const fp = fingerprint(kind + message, extra.source);
  const now = Date.now();
  const last = seen.get(fp);
  if (last && now - last < DEDUPE_MS) return;
  seen.set(fp, now);
  const body = {
    message: `[${kind}] ${message}`,
    stack: extra.stack || "",
    source: extra.source || location.pathname,
    lineno: extra.lineno,
    colno: extra.colno,
    url: location.href,
  };
  try {
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => {});
  } catch { /* 忽略 */ }
}

export function initErrorReporter() {
  window.addEventListener("error", (e) => {
    report("js-error", e.message || "unknown", {
      source: e.filename, lineno: e.lineno, colno: e.colno, stack: e.error?.stack,
    });
  });
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason;
    report("promise", r?.message || String(r), { stack: r?.stack });
  });

  // API 5xx / 网络失败也记录（后端 errorhandler 已记一份，这里补上请求上下文）
  const origFetch = window.fetch;
  window.fetch = async (...args) => {
    try {
      const resp = await origFetch(...args);
      if (resp.status >= 500) {
        const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
        report("api-5xx", `HTTP ${resp.status} ${url}`, {});
      }
      return resp;
    } catch (err) {
      const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
      report("api-network", `${err?.message || err} ${url}`, {});
      throw err;
    }
  };
}
