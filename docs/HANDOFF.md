# Resume Studio 重构 · 交付文档（HANDOFF）

> **用途**：把项目完整交接给下一个 Agent。
> **阅读顺序**：§1 三十秒摘要 → §4（Phase 2 待办）→ 其余按需查。
> 配套文档：`README.md`（产品说明 + 快速开始）｜`docs/SPEC.md`（完整规格）｜`docs/research/`（4 路调研原始产出）

---

## 1. 三十秒摘要

**项目**：`resume-builder` —— 排版优先的简历产品（Python + Flask 后端 + 原生 ES Modules 前端，无构建步骤）。

**当前状态（2026-09-24）**：**Phase 1（排版）全部完成**：

| 事项 | 状态 |
|---|---|
| PDF 中文字体 Type3 降级（原 P0 阻塞） | ✅ **已解决**：CFF OTF → glyf TTF + 剥离部首 cmap，全模板 Type0、中文可检索 |
| 前端编辑器（`static/`） | ✅ **已从零完成**：12 个文件，全部交互经真实浏览器验证 |
| 正式测试套件 | ✅ **pytest 108 用例全绿**（字体 / 分页 / ATS / 迁移 / PDF 导入 / 视觉回归 / 新功能回归） |
| 视觉走查 | ✅ 6 套模板 → PDF → PNG 逐套检查通过，且有基线像素回归测试 |
| 优化轮（导出自检 / 自动适应 / 自有字体 / 版本历史 / HTML 导出 / undo / i18n / CI） | ✅ **已完成并经浏览器 10/10 走查**，详见 §3.0 |
| README / git init / 清理 | ✅ 已完成（`.gitignore` 规范，含 CI 工作流） |

**下一个 Agent 要做的事**：只剩 **Phase 2 产品化剩余项**（§4.2）：JD 关键词匹配 / ATS 检查、LLM 润色、模板预览图。用户已确认的技术决策见 §2，**不要重新讨论**。

---

## 2. 背景与已确认决策

| 决策点 | 选择 |
|---|---|
| 技术栈 | **保留 Python + Flask**。本机 Python 3.12.10 |
| AI 能力 | **接入 LLM API**（OpenAI 兼容协议，用户提供 key）→ Phase 2 |
| 节奏 | **两步走**：Phase 1 排版优先（✅ 已完成），Phase 2 产品化 |
| 前端形态 | 原生 ES Modules，**无构建步骤**（双击 `python app.py` 即用） |

**环境事实**：Windows，项目根 `E:\pythonProject\resume-builder`，git 仓库已初始化。Playwright Chromium 151 可用。端口 5000。

---

## 3. ✅ 已验证基线（本轮实测）

| 验证项 | 结果 |
|---|---|
| `python -m pytest tests/ -q` | ✅ **78 / 78 通过**（约 40s，含真实 Chromium 渲染） |
| `python app.py` 真实启动 + 前端走查 | ✅ 真实浏览器加载零 console 错误；9/9 交互用例通过（编辑联动 / 自动保存 / 区块显隐排序增删 / 自定义区块全流程 / JSON 应用 / Ctrl+S / 模板切换） |
| 6 套模板渲染（×2 示例） | ✅ 语义标记完整（`.r-sheet`/`.rsec[data-section]`/`.ritem`/`.rlist`…） |
| 6 套模板 PDF 字体 | ✅ 全部 Type0 子集 + 中文可检索（pymupdf 与 pdfplumber 双库验证） |
| 分页 | ✅ 1/2/3 页构造页数正确、无空白页、手动分页点正确换算页数 |
| 导出 pdf / docx / json | ✅ 魔数正确，前端 blob 下载触发正常 |
| 导入 JSON（v2 + v1 迁移） | ✅ v1 数据正确迁移；导入换发新 id 不覆盖已有简历 |
| 旧版 `/api/*` 兼容层 6 端点 | ✅ 全部桥接成功 |
| 编辑器导入 PDF / 模板 | ✅ 后端单测通过（前端弹窗交互已走查） |

### 3.0 优化轮新增能力（2026-09-24 晚，全部经真实浏览器验证）

| 能力 | 后端 | 前端 |
|---|---|---|
| 导出 PDF 字体自检 | `api/export.py` `_pdf_quality_warnings()` → `X-Resume-Warnings` 响应头 | `api.js postDownload` 读取并 toast |
| 一键适应一页 | `services/autofit.py` 压缩阶梯迭代测量（行距→字号→间距→边距） | 设计面板「⚡ 自动适应一页」 |
| 用户自有字体 | `services/font_manager.py`（上传→CFF 转换→部首清洗→注册）+ `api/fonts.py` | 设计面板字体组（列表 / 上传 / 使用 / 删除） |
| 历史版本 | `services/documents.py` `document_versions` 表（每文档 20 份快照）+ WAL | 简历列表「⏱」→ 版本弹窗（恢复） |
| HTML 自包含导出 | `exporters/html_export.py`（字体 base64 内嵌） | 顶栏「存 HTML」 |
| 撤销 / 重做 | —（纯前端） | `store.js` 编辑突发快照 + Ctrl+Z / Ctrl+Y |
| 分页线精确化 | `pdf_worker.py` 返回 `effTop` / `breaks` | `pagination.js` 打印坐标反算 |
| i18n（中 / 英） | — | `static/js/i18n.js` + 顶栏「EN / 中」 |
| 临时文件清理 | `engine/pdf.py sweep_stale_renders()`（启动时清扫 >1h 残留） | — |
| photo 安全 | `sections.py _safe_photo_src()`（仅 http(s) / 站内路径） | — |
| CI | `.github/workflows/ci.yml`（Windows + Playwright） | — |

**修过的坑（代码已验证，勿重复排查）**：

| # | 症状 | 根因 | 修复 |
|---|---|---|---|
| 1 | 表单编辑不进预览 | `setByPath(store.doc.content, path)` 但 path 已含 `content.` 前缀 → 写进嵌套的 `content.content` | 改 `setByPath(store.doc, …)` |
| 2 | 保存后表单写入失效 | `saveNow()` 用服务端返回文档整体替换 `store.doc`，已渲染表单持有旧对象引用 | 保留客户端对象，仅同步 `updatedAt` |
| 3 | 导入 JSON 覆盖原简历 | PUT 按 id upsert，导入文档带旧 id | `/api/v1/import/json` 换发新 uuid |
| 4 | `sample_general()` 被污染 | `sample.py _build` 浅合并，返回文档与模块级 `_SAMPLE_GENERAL` 共享列表 | `copy.deepcopy(content)` |
| 5 | tech 模板出现 Type3 | 等宽字体栈 `ui-monospace, "Cascadia Mono", "Consolas", monospace` 前两个回退不可嵌入 | 改 `"Consolas", "Courier New", "Noto Sans SC", monospace` |
| 6 | 页码徽章不计手动分页 | measure JS 只按 scrollHeight 算页数，`.r-pagebreak` 高度为 0 | 累计页尾浪费模型换算有效坐标 |
| 7 | `verify_pdf_fonts` 永远 ok | Type3 的 basefont 是空串被 `if basefont:` 过滤 | 不过滤空名 + 要求提取出真正汉字（`[\u4e00-\u9fff]`） |
| 8 | 表单改名后 Ctrl+Z 无效 | 撤销换了文档对象但表单不重渲染，输入框显示旧值 | `setDocument` 发 `doc-swapped` 事件 → 表单 / 区块树重画 |
| 9 | undo 拍到的是变更后的值 | `touch()` 在 mutate 之后调用，快照已是新值 | 改为「突发静默后固化 `_lastStable`，突发开始把它入栈」 |
| 10 | 分页模式不画线 | 进入时 `pageInfo` 非空（过期的 1 页数据）就不重新测量 | 进入分页模式**总是**重新测量；结果更新时重画覆盖层 |
| 11 | 压缩阶梯 0.86/0.84/0.82/0.80 四档空转 | schema 把 fontScale 硬钳到 ≥0.90 | `DESIGN_LIMITS.fontScale` 下限放宽到 0.80（8.4pt 仍是可读下限） |
| 12 | `api.getJson is not a function` | `api` 对象没挂基础方法，designPanel / sidebar 直接调 | api 对象补 `getJson/postJson/putJson/del` |

---

## 4. 待完成（Phase 2 产品化）

### 4.1 字体问题的完整结论（已完成，存档备查）

Chromium PDF 后端对 CFF 轮廓 web font 降级为 Type3。解决链：

1. `tools/otf2ttf.py` 把 5 个 Noto OTF 转成 glyf TTF（每文件约 30–50s，**必须后台跑**）
2. **康熙部首 cmap 缺陷**（调研盲区，本轮实证）：Noto CJK 的 cmap 中 208 个部首（U+2F00–U+2FDF）与汉字共用字形，Chromium 构建 ToUnicode 时按字形反查会命中部首码位（⾼ U+2FBC 而非 高 U+9AD8）→ pdfplumber/pdfminer 提取乱码（pymupdf 不受影响）。`tools/strip_radical_cmap.py` 已剥离（每字体 1316 条 cmap 记录）
3. `fonts/` 只保留 `.ttf`，`engine/tokens.py` 的 `FONT_FILES` 已指向 `.ttf`
4. 等宽字体栈必须指向可嵌入字体（见 §3 坑 #5）

**回归测试**：`tests/test_pdf_fonts.py`（改字体相关代码后必跑）。

### 4.2 Phase 2 剩余功能（按建议顺序）

> 优化轮已完成：自有字体上传、自动适应一页、历史版本、HTML 导出、导出自检、undo、i18n、CI。
> **已决策保留**：`/api/*` 旧版兼容层继续保留（用户可能还开着 v1 页面，删除是产品决策不是技术决策）。

1. **JD 关键词匹配 / ATS 检查**（`services/analyze.py` + `api/analyze.py`）
   - 输入 JD 文本 → 提取关键词（权重：硬技能 > 教育 > 职位 > 软技能）→ 与简历比对 → 匹配率 + 缺失建议
   - 纯本地实现，无需外部 API；建议匹配率阈值 ≥75%
   - 前端入口：编辑器左栏加「分析」页签，或顶栏按钮 + 结果弹窗
2. **LLM 内容润色**（`services/llm.py` + `api/llm.py`）
   - OpenAI 兼容协议（base_url / api_key / model 用户可配，**存本地配置，不要提交 key**）
   - 能力：bullet 按 Google XYZ 公式润色、按 JD 定制改写、量化成果建议
   - 前端入口：表单字段旁的「AI 润色」按钮 + 设置弹窗
3. 模板预览图：每套模板一张 `preview.png`，模板菜单显示（可复用 `test_visual_regression` 的渲染逻辑生成）

---

## 5. 前端编辑器现状（`static/`，已交付）

```
static/
├── editor.html              # 页面骨架（顶栏 + 三栏 + 4 个弹窗 + toast 容器）
├── editor.css               # 编辑器样式（与简历模板 CSS 完全分离）
└── js/
    ├── app.js               # 入口：boot / 顶栏 / 模板菜单 / 页签 / 快捷键
    ├── store.js             # 状态 + 防抖（预览 300ms / 保存 800ms / 页码 1.4s）+ localStorage 双写
    ├── api.js               # fetch 封装 + 全部端点
    └── components/
        ├── sidebar.js       # 区块树（拖拽/排序/显隐/重命名/删除）+ 文档列表 + 确认弹窗
        ├── form.js          # schema 驱动表单（text/date/textarea/list/rating × object/array/skills/simple）
        ├── designPanel.js   # 设计参数面板（compact 时滑块联动禁用并显示生效值）
        ├── preview.js       # iframe srcdoc 预览 + 页码徽章 + 缩放
        ├── pagination.js    # 分页模式：注入分页线 + 区块「在此分页」按钮 + 建议分页一键应用
        ├── jsonEditor.js    # JSON 编辑弹窗 + 导入弹窗（JSON/PDF/模板）
        └── toast.js         # 通知
```

**已验证的交互**：编辑→预览联动、自动保存状态、区块显隐/排序/增删/重命名、自定义区块全流程（含内容进预览）、JSON 应用、Ctrl+S、模板切换（含主题色联动）、compact/dateAlign/accent/serif 设计控件、分页模式（两页内容出分页线 + 按钮激活态 + 应用建议）、导出 PDF/Word/JSON 下载、JSON 导入（新建文档）、文档列表切换/复制/删除、刷新后恢复。

**关键约定**：
- 表单路径统一为 `content.<section>.<idx>.<field>`，写入 `store.doc` 后 `store.touch()`
- `store.doc` 对象在保存后**不整体替换**（闭包引用问题，见 §3 坑 #2）
- 预览 iframe 同源（`srcdoc` + `/fonts` 相对 URL），可直接访问 `contentDocument`
- 空数组区块在预览中不渲染（内容为空 → 自然实现「一页」约束），加条目并填写后才出现

---

## 6. 架构参考

### 6.1 渲染管线

```
normalize_document(doc)                      # schema.py：收敛形状 + v1 迁移
  → list_templates() / get_template(id)      # 扫描 templates/*/template.json
  → render_body_html()                       # sections.py：区块 → 规范化 HTML
      ├─ 每个区块 → .rsec/.ritem/.rlist 语义标记
      └─ pageBreaks 中的 key → 前插 <div class="r-pagebreak">
  → Jinja2 渲染 <template>/layout.html       # 只写结构：top/sidebar/main 三槽位
  → 组装完整 HTML：
      @font-face   preview→/fonts，pdf→file:/// 绝对路径（.ttf）
      @page        { size: A4; margin: <mm> }   ← 字面量，不用 CSS 变量
      :root        设计令牌 CSS 变量
      base_css     重置 + 语义标记默认样式 + 中文排版 + 打印分页规则
      layout.css   模板视觉差异化
```

**核心设计**：所有模板共享同一套区块 HTML 标记，视觉差异**只**由模板 CSS 决定。好处：排版质量一致、打印规则只写一份、自定义区块自动获得全部模板支持。

### 6.2 slot 分配

`template.json` 声明 `slots: {top:[...], sidebar:[...], main:[...]}`，未列出的进 `main`。`layout.html` 用 `top_sections` / `sidebar_sections` / `main_sections` 取用。注意 `body_class` 是加在 `.r-sheet` 上（不是 `<body>`）。

### 6.3 iframe 内可用的语义标记（分页 UI 靠这些定位，勿改）

```
.r-sheet                页面容器（A4 纸张，794×1123px @96dpi）
  .rsec[data-section]   每个区块（profile/workExperiences/projects/educations/skills/selfEvaluation/custom/自定义key）
    .rsec-title         区块标题
    .rsec-body
      .ritem            条目（工作/项目/教育的一条记录）
        .ritem-head > .ritem-heading(.ritem-title + .ritem-sub) + .ritem-date
        .rlist > li     职责描述列表
      .rskills > .rskill > .rskill-name + .rrate
      .rtag-row > .rtag 技能标签
  .r-pagebreak          手动分页锚点（高度 0，break-before: page）
```

### 6.4 数据模型

```python
Document = {
  "id": "uuid hex", "title": str, "templateId": str,
  "design": {...},                  # fontFamily/fontScale/lineHeight/sectionGap/pageMargin/accent/dateAlign/showPhoto/compact
  "sections": [ SectionConfig ],    # 顺序即渲染顺序
  "content": {...},                 # 各区块数据
  "pageBreaks": [sectionKey, ...],  # 手动分页点
  "version": 2, "createdAt": float, "updatedAt": float,
}
SectionConfig = {"key","title","type":"object|array|simple|skills","fields":[FieldDef],"visible":bool}
FieldDef = {"key","label","type":"text|date|textarea|list|rating"}
```

内置区块（`registry.py`，7 个）：`profile`(object) / `workExperiences`(array) / `projects`(array) / `educations`(array) / `skills`(skills) / `selfEvaluation`(simple) / `custom`(simple)。

**旧数据兼容**：`schema.migrate_legacy()` 转 v1 的 `_sections`+扁平 content；`json_io.import_document()` 接受新版信封/裸文档/v1 三种输入。

### 6.5 设计参数默认值

| 字段 | 默认 | 范围 |
|---|---|---|
| `fontFamily` | `sans` | sans / serif |
| `fontScale` | 1.0 | 0.90–1.15 |
| `lineHeight` | 1.45 | 1.20–1.80 |
| `sectionGap` | 18 | 8–32 px |
| `pageMargin` | 20 | 12.7–25 mm（硬下限 0.5in） |
| `accent` | `#0f766e` | hex |
| `dateAlign` | `right` | right / below |
| `showPhoto` | false | bool |
| `compact` | false | bool（一键压缩：0.94/1.32/12px/15mm） |

---

## 7. 测试与运行

```bash
cd E:\pythonProject\resume-builder
$env:PYTHONPATH = 'E:\pythonProject\resume-builder'   # 必须，否则 ModuleNotFoundError

python app.py                        # 启动（http://localhost:5000）
python -m pytest tests/ -q           # 78 用例（PDF 用例真实起 Chromium，约 40s）
python tests/debug_pdf_fonts.py      # 诊断 PDF 字体原始信息 + 页面图
```

### ⚠️ 环境坑（都踩过）

1. **跑 Python 必须设 `PYTHONPATH`**（或在项目根执行）。
2. **PowerShell 里不要用多行 `python -c "..."`**——写成 .py 文件再跑。
3. **重启服务器前先杀旧进程**：`netstat -ano | findstr :5000` 找 PID 再 `taskkill /F /PID <pid>`；直接 `taskkill /IM python.exe` 会误杀。旧进程不退会拿到旧代码（本次实测踩过：改了后端但请求打到旧服务）。
4. **`page.pdf()` 不接受 BytesIO**，必须传文件路径再读回。
5. **字体转换很慢**（31k 字形，每文件 30–50s），后台跑。
6. **测试夹具用函数作用域**（`sample_general()` 已深拷贝，但共享状态仍是常见污染源）。
7. `data/resumes.db` 是运行时生成物，测试用临时库（见 `tests/conftest.py` 的 monkeypatch）。

---

## 8. 其他备注

- `legacy/` 是 v1 全部源码归档，**不参与运行、未纳入 git**（`.gitignore` 已排除）。
- `docs/research/` 的调研结论已全部提炼进代码与 README，**无需重做调研**。
- 中文字体为 Noto Sans SC / Noto Serif SC，**SIL OFL 1.1 许可**，可自由使用嵌入再分发。
- 旧版 `/api/export-html-pdf` 端点**未迁移**（v1 用前端改过的 HTML 直出 PDF）；新架构下由 `/api/v1/render` + `pageBreaks` 覆盖，如确需保留再加。
- 目标长期愿景：`goal-92e93b2d-75cd-4cb7-83db-5b106c5b89af`。
