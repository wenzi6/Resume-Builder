/**
 * 全局状态：文档、模板、schema + 防抖自动保存 + localStorage 兜底。
 *
 * 数据流：组件 mutate store.doc -> store.touch() -> 防抖调度：
 *   - 300ms  -> 重新渲染预览（emit 'preview'）
 *   - 800ms  -> PUT 保存到后端 + 写 localStorage（emit 'saved' / 'dirty'）
 */

const LS_PREFIX = "resume-studio:autosave:";
const PREVIEW_DEBOUNCE = 300;
const SAVE_DEBOUNCE = 800;
const PAGEINFO_DEBOUNCE = 1400;

function deepClone(v) {
  return structuredClone(v);
}

class Store {
  constructor() {
    this.state = {
      doc: null,            // 当前文档（Document）
      templates: [],        // 模板列表
      schema: null,         // {builtin, builtinKeys, customArrayFields, customSimpleFields}
      documents: [],        // 文档列表（轻量元信息）
      loading: true,
      paginationMode: false,
      pageInfo: null,       // page-info 结果
      zoom: 1,
    };
    this._listeners = new Map(); // event -> Set<fn>
    this._previewTimer = null;
    this._saveTimer = null;
    this._pageInfoTimer = null;
    this._dirty = false;
    this._saving = false;
    this._lastSavedAt = null;
    this._saveError = null;
  }

  // ---------- 订阅 ----------
  on(event, fn) {
    if (!this._listeners.has(event)) this._listeners.set(event, new Set());
    this._listeners.get(event).add(fn);
    return () => this._listeners.get(event).delete(fn);
  }

  emit(event, payload) {
    const set = this._listeners.get(event);
    if (set) for (const fn of set) fn(payload);
    const all = this._listeners.get("*");
    if (all) for (const fn of all) fn(event, payload);
  }

  // ---------- 初始化 ----------
  init({ doc, templates, schema, documents }) {
    this.state.templates = templates || [];
    this.state.schema = schema || null;
    this.state.documents = documents || [];
    this.state.doc = doc || null;
    this.state.loading = false;
    this.emit("init");
    this.emit("doc", this.state.doc);
  }

  // ---------- 文档访问 ----------
  get doc() {
    return this.state.doc;
  }

  get templates() {
    return this.state.templates;
  }

  get schema() {
    return this.state.schema;
  }

  /** 标记内容已变更：调度预览刷新与自动保存。 */
  touch(options = {}) {
    if (!this.state.doc) return;
    this.state.doc.updatedAt = Date.now() / 1000;
    this._dirty = true;
    this.emit("doc", this.state.doc);
    this._schedulePreview();
    this._scheduleSave();
    if (options.pageInfo) this._schedulePageInfo();
  }

  /** 仅刷新预览（如缩放、模板切换后强制重渲染）。 */
  refreshPreview() {
    this._schedulePreview(0);
  }

  // ---------- 防抖调度 ----------
  _schedulePreview(delay = PREVIEW_DEBOUNCE) {
    clearTimeout(this._previewTimer);
    this._previewTimer = setTimeout(() => {
      this._previewTimer = null;
      this.emit("preview");
    }, delay);
  }

  _scheduleSave(delay = SAVE_DEBOUNCE) {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null;
      this.saveNow();
    }, delay);
  }

  _schedulePageInfo(delay = PAGEINFO_DEBOUNCE) {
    clearTimeout(this._pageInfoTimer);
    this._pageInfoTimer = setTimeout(() => {
      this._pageInfoTimer = null;
      this.emit("pageinfo");
    }, delay);
  }

  // ---------- 保存 ----------
  async saveNow() {
    const doc = this.state.doc;
    if (!doc || !doc.id) return;
    if (this._saving) {
      // 保存中：重新调度，保存完后再来
      this._scheduleSave(300);
      return;
    }
    this._saving = true;
    this.emit("save-state", "saving");
    this._writeLocal(doc);
    try {
      const { api } = await import("./api.js");
      const saved = await api.saveDocument(doc.id, doc);
      // 保留客户端文档对象（表单/树的闭包都持有它），只同步服务端时间戳。
      // 整体替换会让已渲染表单持有过期引用，导致后续编辑写入旧对象。
      if (this.state.doc === doc && saved && typeof saved === "object") {
        doc.updatedAt = saved.updatedAt ?? doc.updatedAt;
        doc.id = saved.id ?? doc.id;
      }
      this._dirty = false;
      this._saveError = null;
      this._lastSavedAt = Date.now();
      this.emit("save-state", "saved");
    } catch (e) {
      this._saveError = e.message;
      this.emit("save-state", "error", e.message);
    } finally {
      this._saving = false;
    }
  }

  get dirty() {
    return this._dirty;
  }

  get lastSavedAt() {
    return this._lastSavedAt;
  }

  // ---------- localStorage 兜底 ----------
  _lsKey(id) {
    return LS_PREFIX + id;
  }

  _writeLocal(doc) {
    try {
      localStorage.setItem(this._lsKey(doc.id), JSON.stringify(doc));
    } catch {
      /* 存储超限等情况忽略 */
    }
  }

  readLocal(id) {
    try {
      const raw = localStorage.getItem(this._lsKey(id));
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  clearLocal(id) {
    try {
      localStorage.removeItem(this._lsKey(id));
    } catch {
      /* ignore */
    }
  }

  // ---------- 文档切换 ----------
  setDocument(doc) {
    clearTimeout(this._saveTimer);
    this._saveTimer = null;
    this.state.doc = doc;
    this.state.pageInfo = null;
    this._dirty = false;
    this._writeLocal(doc);
    this.emit("doc", doc);
    this.refreshPreview();
  }

  setDocuments(list) {
    this.state.documents = list || [];
    this.emit("documents", this.state.documents);
  }

  setTemplates(list) {
    this.state.templates = list || [];
    this.emit("templates", this.state.templates);
  }

  // ---------- 分页模式 ----------
  setPaginationMode(on) {
    this.state.paginationMode = !!on;
    this.emit("pagination", this.state.paginationMode);
  }

  setPageInfo(info) {
    this.state.pageInfo = info;
    this.emit("pageinfo-result", info);
  }

  // ---------- 缩放 ----------
  setZoom(z) {
    this.state.zoom = Math.max(0.5, Math.min(1.5, Math.round(z * 100) / 100));
    this.emit("zoom", this.state.zoom);
  }

  // ---------- 内容操作辅助（组件通过 store.doc 直接 mutate 后调 touch） ----------

  /** 取区块数据容器（兼容 dict / list / str 三种存储形状）。 */
  sectionContent(key) {
    const c = this.state.doc?.content || {};
    return c[key];
  }

  cloneDoc() {
    return deepClone(this.state.doc);
  }
}

export const store = new Store();

/** 常用内容工具（纯函数，输入 doc 的 content 与 section 定义）。 */
export const contentUtil = {
  /** list 类型字段的读取（兼容 array / {descriptions:[]} / string）。 */
  readList(container) {
    if (Array.isArray(container)) return container.slice();
    if (container && Array.isArray(container.descriptions)) return container.descriptions.slice();
    if (typeof container === "string" && container.trim()) return container.split(/\n+/).filter(Boolean);
    return [];
  },

  /** 确保 content[key] 是 {descriptions: []} 形状（simple / skills）。 */
  ensureDict(content, key) {
    if (!content[key] || typeof content[key] !== "object" || Array.isArray(content[key])) {
      content[key] = { descriptions: [] };
    }
    if (!Array.isArray(content[key].descriptions)) content[key].descriptions = [];
    return content[key];
  },

  /** 确保 content[key] 是数组（array 类型区块）。 */
  ensureArray(content, key) {
    if (!Array.isArray(content[key])) content[key] = [];
    return content[key];
  },
};
