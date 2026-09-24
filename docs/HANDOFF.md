# Resume Studio 重构 · 交付文档（HANDOFF）

> **用途**：把项目完整交接给下一个 Agent。
> **阅读顺序**：§1 三十秒摘要 → §4（🔴 P0 必看）→ §5（前端 spec，主体待办）→ 其余按需查。
> 配套文档：`docs/SPEC.md`（完整规格）｜`docs/research/`（4 路调研原始产出，结论已提炼进本文，**无需重做调研**）

---

## 1. 三十秒摘要

**项目**：把 `resume-builder`（原为能用的本地简历脚本）重构为长期使用的简历产品，第一优先级**排版完美**。

**当前状态**：后端 + 模板引擎 + 6 套模板 + PDF/Word/JSON 导出 + SQLite 持久化 + 分页测量**已全部完成并通过自动化验证（39/41 用例）**。唯一未开始的是**前端编辑器**（`static/` 是空目录）。

**下一个 Agent 要做三件事**：

| # | 事项 | 详见 |
|---|---|---|
| 1 | 🔴 **解决 PDF 中文字体 Type3 降级问题**（阻塞级，其他都做完也没法用） | §4 |
| 2 | **写前端编辑器**（`static/` 从零开始，约 6-8 个文件） | §5 |
| 3 | Phase 1 收尾：正式测试套件、视觉走查、README、git init | §6 |

---

## 2. 背景与已确认决策

用户明确确认过三点（**不要重新讨论**）：

| 决策点 | 选择 |
|---|---|
| 技术栈 | **保留 Python + Flask**。本机 Python 3.12.10，依赖已就绪：flask 3.1.3 / flask-cors / playwright / python-docx / pdfplumber / fonttools 4.64 / pymupdf |
| AI 能力 | **接入 LLM API**（OpenAI 兼容协议，用户提供 key）→ Phase 2 |
| 节奏 | **两步走**：Phase 1 排版优先，Phase 2 产品化 |

长期目标（goal）：`goal-92e93b2d-75cd-4cb7-83db-5b106c5b89af`，`maxGoalRounds=40`，objective 见 goal 记录。

**环境事实**：Windows，项目根 `E:\pythonProject\resume-builder`。Playwright Chromium 151.0.7922.34 已安装可用。项目**不是 git 仓库**。

---

## 3. ✅ 已验证基线（本轮实测，非估计）

用 `tests/api_e2e.py`（Flask test client，39/41 通过）+ 真实 `python app.py` 启动验证：

| 验证项 | 结果 |
|---|---|
| `python app.py` 真实启动 | ✅ `/healthz` 200、`/api/v1/templates` 返回 6 套 |
| 6 套模板渲染（×2 份示例数据） | ✅ `tests/smoke_render.py`，0 失败 |
| 文档 CRUD + duplicate + from-sample | ✅ |
| `/api/v1/render` × 4 模板 | ✅ HTML 含数据、含 `.r-sheet` |
| `/api/v1/page-info`、`/api/v1/auto-pagebreaks` | ✅ 返回页数/落位/建议分页点 |
| 导出 pdf / docx / json | ✅ 魔数正确（`%PDF` / `PK` / `{`） |
| 导入 JSON（v2 + v1 迁移） | ✅ v1 数据正确迁移（王五用例） |
| 导入模板 zip / html + 路径穿越防护 | ✅ 穿越返回 400 |
| 旧版 `/api/*` 兼容层 5 个端点 | ✅ 全部桥接成功 |
| 边界情况 8 项（空 body / 坏 JSON / 未知 id / 未知模板 / 数组 body） | ✅ 全部不崩、返回合理状态码 |
| PDF 管线 | ⚠️ 能出 PDF、页数正确、无残留文件，**但字体是 Type3 → 见 §4** |

**唯一 2 个失败用例是预期的**：`GET /` 和 `GET /static/editor.css` 返回 404 —— 因为前端还没写。

---

## 4. 🔴 P0 阻塞：PDF 中文字体降级为 Type3

### 4.1 现象

`tests/smoke_pdf.py` 报告 `type3=0`、`textExtractable=True`，**看似通过，实为假象**（校验函数有 bug，见 4.4）。真实情况：

```
classic 模板导出的 PDF：103 个 Type3 字体，basefont 全为空字符串
文本层乱码：'����\n�߼�ǰ�˹���ʢ\n...'（UTF-8 字节被当 Latin-1 解）
tech 模板导出的 PDF：1 个 Type0 字体，名字 NSimSun（回退到系统宋体）
```

后果：文本不可检索、不可复制、**ATS 完全无法解析**（ATS 要求"文本型 PDF"）。这是致命问题。

### 4.2 根因（已用对照实验实证）

`tests/debug_outline.py` 的实验结果：

| 字体文件 | 轮廓格式 | 隔离测试（@font-face 未加载→回退系统字体） | 真实管线（@font-face 加载成功） |
|---|---|---|---|
| `SourceHanSansSC-Medium.ttf` | **glyf** | Type0 ✅ | — |
| `NotoSansSC-Regular.otf`（项目在用） | **CFF** | Type0 ✅（回退 MicrosoftYaHei） | **Type3 ❌** |
| `NotoSerifSC-Regular.otf` | **CFF** | Type0 ✅（回退） | **Type3 ❌** |

**结论：Chromium/Skia 的 PDF 后端无法正确嵌入 CFF 轮廓的 web font，会降级为 Type3；只有 glyf 轮廓才能嵌入为 Type0 CID 子集。**

⚠️ 这是调研的盲区：4 路调研只验证过 TTF/TTC（得到 `AAAAAA+SourceHanSansSC-Medium`），**没有测 CFF OTF**。已实证补上，**不要再重复调研**。

### 4.3 旁证：旧版服务的日志

停止上一个 Agent 留下的 v1 Flask 服务时，日志里密集出现：

```
Could not get FontBBox from font descriptor because None cannot be parsed as 4 floats
```

（在 `POST /api/import-pdf` 调用附近，来自 pdfminer）。这正是解析**字体描述符损坏的 PDF** 时的报错——说明**旧版导出的 PDF 早就中招**，只是没人注意。修复后可用这条日志做前后对比。

### 4.4 解决方案（按推荐顺序）

**方案 A（推荐）：本地把 CFF OTF 转成 glyf TTF**

转换器已写好：`tools/otf2ttf.py`（fontTools 官方配方，Cu2QuPen 三次→二次贝塞尔 + 重建 glyf/loca/maxp/post）。

```bash
python tools/otf2ttf.py fonts/NotoSansSC-Regular.otf fonts/NotoSansSC-Regular.ttf
```

⚠️ **上次执行在 600s 超时内未完成被中断**（31,036 字形，转换很慢）。下一个 Agent 应当：
1. 用 `run_in_background: true` 跑，不要前台等；
2. 或先只转 Regular 一个，验证通过再批量；
3. 转完**删除 `fonts/*.otf`**，只保留 `.ttf`，并把 `engine/tokens.py` 的 `FONT_FILES` 扩展名改成 `.ttf`；
4. **验收标准**（必须同时满足）：
   - PDF 内字体为 **Type0**（而非 Type3）
   - `page.get_text()` 返回**正确中文**（能匹配到"张三"，不是乱码）
   - 可用 `tests/debug_outline.py` / `tests/debug_pdf_fonts.py` 验证

**方案 B（备选，最快）：改用系统 TTF 字体**

Windows 自带 `Microsoft YaHei` / `SimSun` / `SimHei` / `DengXian`（均为 glyf TTF）。隔离实验证明系统字体会被嵌入为 Type0 且正常。做法：清空 `engine/tokens.py` 的 `FONT_FILES`，字体栈只留系统字体名。缺点：换机器外观不一致、产品不自包含。**仅作快速验证排版效果的过渡方案。**

**方案 C：从网络获取静态 TTF**（用前必须实测）

- Google Fonts CSS API 旧 UA 只返 **woff**（`https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700`，UA 用 `Mozilla/5.0 (Windows NT 6.1; rv:27.0) Gecko/20100101 Firefox/27.0`）——woff 内若是 CFF 仍会 Type3；
- jsDelivr `@fontsource/noto-sans-sc` 提供 woff2（按 unicode-range 拆分）；
- GitHub API 当时 403 rate limit，未列出 noto-cjk 仓库结构。

### 4.5 顺手要修的 bug

`resume_builder/engine/pdf.py` 的 `verify_pdf_fonts()` **校验失效**：Type3 字体的 `basefont` 是空字符串，被 `if basefont:` 过滤掉，导致 `type3` 永远为空、永远 `ok=True`。必须改成：

```python
for f in page.get_fonts(full=True):
    ftype, basefont = f[2], f[3] or "(unnamed)"
    types[basefont] = ftype          # 不过滤空名
    if "Type3" in ftype:
        type3.append(basefont)
```

并且 `ok` 必须同时要求：无 Type3、`textExtractable`、且 `textSample` 能匹配到已知中文字符（如"张三"）——否则乱码文本也会被判通过。

---

## 5. 本轮发现并已修复的 bug（代码已验证可用）

以下都是**实测发现并已修好**的，下一个 Agent 不需要再排查；列出是为了让你相信当前代码是干净的，并了解几个容易复发的模式：

| # | 症状 | 根因 | 修复 |
|---|---|---|---|
| 1 | `create_app()` 直接 ImportError，**应用根本起不来** | `exporters/docx.py` 写 `from . import typo`，但 typo 在 `engine/` 下 | 改 `from ..engine import typo` |
| 2 | `register_blueprints` ImportError | 文件叫 `export.py`，导入写 `exports` | 统一为 `export` |
| 3 | `POST /api/v1/export/*` 报 `too many values to unpack` | 编辑残留，`return x, None, None` | 改回 2 值 |
| 4 | `POST /api/v1/render` 传数组 body → 500 | `body.get()` 未防非 dict | 三处（render/export/documents）加 `isinstance` 守卫 |
| 5 | 未知模板 ID → `TemplateNotFound` 崩溃 | 元数据回退了，但加载布局文件仍用原 ID | 统一用 `template["id"]`，并防空模板目录 |
| 6 | zip 路径穿越测试后残留 `evil/` 空目录 | 提前 `return` 跳过了清理 | 拒绝前先 `rmtree(dest_dir)` |

**遗留的小模式**（可选修）：`api/templates.py` 的 `_validate_html_template` 里有两个空 `if` 分支（`pass`），是死代码，可清理。

---

## 6. 待完成

### 6.1 P0：解决 §4 的字体问题

### 6.2 P0：写前端编辑器（`static/` 目录，从零开始）

**约束**：原生 ES Modules，**无构建步骤**（用户要求双击 `python app.py` 即用）。

#### 文件清单

```
static/
├── editor.html              # 页面骨架（左右分栏 + 弹窗容器）
├── editor.css               # 编辑器自身样式（与简历模板 CSS 完全分离）
└── js/
    ├── app.js               # 入口：import 各组件、初始化、Ctrl+S、全局事件
    ├── store.js             # 状态 + 防抖自动保存（后端 + localStorage 双写）
    ├── api.js               # fetch 封装（统一错误处理）
    └── components/
        ├── sidebar.js       # 文档列表 + 区块树（排序/显隐/重命名/新增/删除）
        ├── form.js          # schema 驱动的表单渲染器
        ├── designPanel.js   # 设计参数面板
        ├── preview.js       # iframe 实时预览 + 页码指示
        ├── pagination.js    # 分页编辑模式（拖拽分页线）
        ├── jsonEditor.js    # JSON 编辑弹窗
        └── toast.js         # 通知
```

#### 初始化 API 调用顺序

```js
const schema  = await GET('/api/v1/schema/sections');   // 驱动表单渲染 ★单一事实来源
const templates = await GET('/api/v1/templates');       // 模板栏（含 defaultDesign）
const docs    = await GET('/api/v1/documents');         // 文档列表
// 无文档时：POST /api/v1/documents/from-sample/general  （或 /tech）
// 有文档时：GET  /api/v1/documents/<id>
```

#### 核心交互契约

| 交互 | 实现要点 |
|---|---|
| 实时预览 | 表单变更 → 300ms 防抖 → `POST /api/v1/render` `{document}` → 写入 iframe。**用 `iframe.srcdoc = html`**（同源，可直接访问 `contentDocument`） |
| 自动保存 | 变更 → 800ms 防抖 → `PUT /api/v1/documents/<id>`；同时写 localStorage 兜底（刷新恢复） |
| 页码指示 | 预览就绪后 → `POST /api/v1/page-info` → 显示"共 N 页"+ 警告（超一页/末页过少） |
| 一键压缩 | 勾选 `design.compact=true` → 重新 render（后端已联动字号/行距/间距/边距） |
| 导出 | `POST /api/v1/export/{pdf,docx,json}`，响应是 blob，前端触发下载 |
| 分页编辑 | 见下 |

#### 分页编辑模式（后端已就绪，只差 UI）

1. 进"分页"模式 → `POST /api/v1/page-info` 拿到每个 `.rsec` 的 `top/height/startPage/endPage`
2. 在 iframe 里按 `top` 画虚线分页线（A4 内容高 = `pageHeightPx`）
3. 用户点某区块标题的"在此分页"→ 把该 section key 加入 `doc.pageBreaks`
4. 保存 → 后端渲染时在该区块前注入 `<div class="r-pagebreak" data-before="key">`
5. 也可调 `POST /api/v1/auto-pagebreaks` 拿建议分页点一键应用

**iframe 内可用的语义标记**（分页 UI 就靠这些定位，勿改）：

```
.r-sheet                页面容器（A4 纸张）
  .rsec[data-section]   每个区块（profile/workExperiences/projects/educations/skills/selfEvaluation/custom/自定义key）
    .rsec-title         区块标题
    .rsec-body
      .ritem            条目（工作/项目/教育的一条记录）
        .ritem-head
          .ritem-heading > .ritem-title + .ritem-sub
          .ritem-date   日期
        .rlist > li     职责描述列表
      .rskills > .rskill > .rskill-name + .rrate
      .rtag-row > .rtag 技能标签
  .r-pagebreak          手动分页锚点
```

#### 设计面板字段 → CSS 变量映射

面板改的值直接写进 `doc.design`，后端编译成 CSS 变量，**前端不需要自己算样式**：

| 面板控件 | doc.design 字段 | 范围 | 对应 CSS 变量 |
|---|---|---|---|
| 字体（黑体/宋体） | `fontFamily` | sans / serif | `--r-font-body` |
| 字号缩放 | `fontScale` | 0.90–1.15 | `--r-fs-body/name/h2/h3/small` |
| 行距 | `lineHeight` | 1.20–1.80 | `--r-lh` |
| 区块间距 | `sectionGap` | 8–32 px | `--r-gap` / `--r-item-gap` |
| 页边距 | `pageMargin` | 12.7–25 mm | `--r-margin` + `@page margin` |
| 主题色 | `accent` | hex | `--r-accent/-soft/-line/-deep/-on-accent` |
| 日期位置 | `dateAlign` | right / below | `--r-date-align` + body class |
| 显示照片 | `showPhoto` | bool | `.r-photo` 显隐 |
| 压缩到一页 | `compact` | bool | 后端联动四参数 |

#### 可从 legacy 移植的逻辑（`legacy/editor_v1.js`，1819 行）

值得移植（v1 已验证过的交互）：
- 动态区块管理：增/删/改/排序/重命名（`defaultSections` / `loadSectionsFromData` / `saveSection` / `moveSection` / `deleteSection`）
- 表单渲染：条目添加/删除/上下移（`renderArrayItem` / `addItem` / `moveItem`）
- JSON 编辑弹窗（`switchToJSON` / `applyJSON`）
- 导入 UI（`initImportUI` / `importPDF` / `importTemplate`）
- 自动保存 + localStorage 恢复（`scheduleAutosave` / `restoreAutosave`）

**不要移植**：
- `buildResumeFromPDF()`（已移到服务端 `services/pdf_import.py`）
- 旧模板引擎相关假设（`_sections`、`{{#if}}` 等）——新引擎是 Jinja2 + slot
- PDF 导入的字体/结构解析（现在走 `/api/v1/import/pdf`，返回完整 document）

### 6.3 P1：Phase 1 收尾

1. 把 `tests/` 里的 debug/smoke 脚本整理成正式 pytest 套件，必须包含：
   - **字体回归**：PDF 内字体为 Type0 且中文可检索（§4.5 修好 `verify_pdf_fonts` 后）
   - **分页回归**：构造 1/2/3 页内容，断言页数正确、无空白页、区块标题不落在页底
   - **ATS 回归**：`ats-plain` 导出的 PDF/DOCX 能被 pdfplumber 提取完整文本
   - **schema 迁移回归**：v1 JSON 导入后字段正确
2. 视觉走查：6 套模板各导一份 PDF → 渲染成 PNG → 逐套检查（间距/对齐/分页/字体/主题色派生）
3. 重写 `README.md`（现在还是 v1 内容）
4. `git init` + `.gitignore`（`output/`、`data/*.db`、`__pycache__/`、`legacy/`、`*.pyc`）
5. 删除 `data/sample-qmjianli.json`（已被 `resume_builder/sample.py` 取代）、清理 `output/` 里的调试产物

### 6.4 P2：Phase 2 产品化

1. **JD 关键词匹配 / ATS 检查**（`services/analyze.py` + `api/analyze.py`）
   - 输入 JD 文本 → 提取关键词（权重：硬技能 > 教育 > 职位 > 软技能）→ 与简历比对 → 匹配率 + 缺失建议
   - 纯本地实现，无需外部 API；建议匹配率阈值 ≥75%
2. **LLM 内容润色**（`services/llm.py` + `api/llm.py`）
   - OpenAI 兼容协议（base_url / api_key / model 用户可配，存本地）
   - 能力：bullet 按 Google XYZ 公式润色、按 JD 定制改写、量化成果建议
   - **key 不要写进代码、不要提交**
3. 模板预览图：每套模板一张 `preview.png`，模板栏显示
4. 多文档管理 UI（基于已实现的 `services/documents.py`）

---

## 7. 架构参考

### 7.1 渲染管线

```
normalize_document(doc)                      # schema.py：收敛形状 + v1 迁移
  → list_templates() / get_template(id)      # 扫描 templates/*/template.json
  → render_body_html()                       # sections.py：区块 → 规范化 HTML
      ├─ 每个区块 → .rsec/.ritem/.rlist 语义标记
      └─ pageBreaks 中的 key → 前插 <div class="r-pagebreak">
  → Jinja2 渲染 <template>/layout.html       # 只写结构：top/sidebar/main 三槽位
  → 组装完整 HTML：
      @font-face   preview→/fonts，pdf→file:/// 绝对路径
      @page        { size: A4; margin: <mm> }   ← 字面量，不用 CSS 变量
      :root        设计令牌 CSS 变量
      base_css     重置 + 语义标记默认样式 + 中文排版 + 打印分页规则
      layout.css   模板视觉差异化
```

**核心设计**：所有模板共享同一套区块 HTML 标记，视觉差异**只**由模板 CSS 决定。好处：排版质量一致、打印规则只写一份、自定义区块自动获得全部模板支持。

### 7.2 slot 分配

`template.json` 声明 `slots: {top:[...], sidebar:[...], main:[...]}`，未列出的进 `main`。`layout.html` 用 `top_sections` / `sidebar_sections` / `main_sections` 取用。

### 7.3 文件地图

```
resume-builder/
├── app.py                        # 入口：python app.py
├── pdf_worker.py                 # Playwright 子进程：pdf / measure 两种模式
├── requirements.txt
├── resume_builder/
│   ├── __init__.py               # create_app() + main()
│   ├── config.py                 # 路径/端口/边距下限/允许的跨域源
│   ├── schema.py                 # Document 模型、归一化、v1→v2 迁移
│   ├── registry.py               # 内置区块注册表（7 区块）★单一事实来源
│   ├── sample.py                 # 两份示例数据
│   ├── engine/
│   │   ├── tokens.py             # 设计参数→CSS变量、@font-face、@page  ★字体文件清单在此
│   │   ├── typo.py               # 盘古之白/日期归一化/分隔符（Jinja filters）
│   │   ├── base_css.py           # 共享基础样式 + 打印分页规则
│   │   ├── sections.py           # 区块 → 规范化 HTML
│   │   ├── renderer.py           # Jinja2 渲染 + slot 分配 + 分页锚点
│   │   └── pdf.py                # 子进程封装 + 分页测量 + 字体校验（§4.5 待修）
│   ├── exporters/
│   │   ├── docx.py               # Word 导出（字号/行距/边距与 HTML 一致）
│   │   └── json_io.py            # JSON 导入导出（含 v1 迁移）
│   ├── services/
│   │   ├── documents.py          # SQLite 持久化
│   │   └── pdf_import.py         # PDF → 结构化文档（从 v1 JS 移植）
│   └── api/                      # /api/v1/* Blueprint + /api/* 旧版兼容层
├── templates/                    # 6 套模板（§8）
├── static/                       # ★ 空！前端待写（§6.2）
├── fonts/                        # 5 个 Noto 静态 OTF（§4 有问题）
├── tests/                        # api_e2e / smoke_render / smoke_pdf / debug_*
├── tools/otf2ttf.py              # CFF→glyf 转换器（§4.4）
├── docs/SPEC.md                  # 完整规格
├── legacy/                       # v1 全部源码归档
└── data/resumes.db               # SQLite（运行时生成）
```

### 7.4 数据模型

```python
Document = {
  "id": "uuid hex", "title": str, "templateId": str,
  "design": {...},                  # §7.5
  "sections": [ SectionConfig ],    # 顺序即渲染顺序
  "content": {...},                 # 各区块数据
  "pageBreaks": [sectionKey, ...],  # 手动分页点
  "version": 2, "createdAt": float, "updatedAt": float,
}
SectionConfig = {"key","title","type":"object|array|simple|skills","fields":[FieldDef],"visible":bool}
FieldDef = {"key","label","type":"text|date|textarea|list|rating"}
```

内置区块（`registry.py`，7 个）：`profile`(object) / `workExperiences`(array) / `projects`(array) / `educations`(array) / `skills`(skills) / `selfEvaluation`(simple) / `custom`(simple)。用户可新增自定义区块（array/simple，字段可配）。

**旧数据兼容**：`schema.migrate_legacy()` 转 v1 的 `_sections`+扁平 content；`json_io.import_document()` 接受新版信封/裸文档/v1 三种输入。

### 7.5 设计参数默认值

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

### 7.6 API

**新版 `/api/v1`**

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/v1/templates` | GET | 模板列表（含 defaultDesign） |
| `/api/v1/schema/sections` | GET | 区块定义，驱动表单渲染 |
| `/api/v1/documents` | GET/POST | 列表 / 新建 |
| `/api/v1/documents/from-sample/<general\|tech>` | POST | 从内置示例创建 |
| `/api/v1/documents/<id>` | GET/PUT/DELETE | 读写删 |
| `/api/v1/documents/<id>/duplicate` | POST | 复制 |
| `/api/v1/render` | POST | `{document}` → 预览 HTML |
| `/api/v1/page-info` | POST | 页数 + 区块落位 + 建议分页点 + 警告 |
| `/api/v1/auto-pagebreaks` | POST | 只返回建议分页点 |
| `/api/v1/export/pdf` `/docx` `/json` | POST | 导出（支持 `{id}` 或 `{document}`） |
| `/api/v1/import/json` | POST | JSON 导入（含 v1 迁移） |
| `/api/v1/import/pdf` | POST | PDF 解析成结构化文档 |
| `/api/v1/import-template` | POST | 模板导入（.html/.zip，有穿越防护） |

**旧版 `/api/*` 兼容层**：`/api/templates`、`/api/sample-data`、`/api/preview/<t>`、`/api/render/<t>`、`/api/export-pdf/<t>`、`/api/export-word/<t>` 已桥接到新实现。

**其他路由**：`GET /`（编辑器，依赖 `static/editor.html`）、`GET /static/<file>`、`GET /fonts/<file>`、`GET /data/<file>`、`GET /healthz`。

---

## 8. 模板体系（6 套，全部完成）

| id | 名称 | 版式族 | atsSafe | 默认主题色 | 说明 |
|---|---|---|---|---|---|
| `classic` | 经典通排 | single | ✅ | `#1f4e79` | 居中页眉 + 底部通栏细线标题，最通用 |
| `modern` | 现代双栏 | sidebar-left | ❌ | `#0f766e` | 渐变通栏页眉 + 左侧 33% 边栏 |
| `minimal` | 极简 | single | ✅ | `#111827` | 无图标、细线分隔、大字距标题、留白多 |
| `professional` | 专业衬线 | single | ✅ | `#7c2d12` | 宋体正文、双线标题、正式稳重 |
| `tech` | 技术深色 | header-band | ❌ | `#1d4ed8` | 深色渐变页眉 + 左侧时间轴 + 等宽日期 |
| `ats-plain` | ATS 纯文本 | single | ✅ | `#000000` | 零颜色零背景零图标，评分条隐藏，标签转纯文本 |

每套 = `template.json` + `layout.html` + `layout.css`。新增模板只需建目录放这三个文件，自动扫描。

---

## 9. 排版规范速查（调研结论，已落地到代码）

| 项目 | 值 | 落地位置 |
|---|---|---|
| 正文 | 10.5pt（×fontScale） | `tokens.py` `--r-fs-body` |
| 姓名 | 17pt bold | `--r-fs-name` |
| 区块标题 | 12.5pt bold | `--r-fs-h2` |
| 条目标题 | 11pt | `--r-fs-h3` |
| 行距 | 1.45 | `--r-lh` |
| 区块间距 | 18px | `--r-gap` |
| 页边距 | 20mm（下限 12.7mm） | `@page` + `.r-sheet` padding |
| 日期 | 右对齐 / 可切"标题下" | `--r-date-align` |
| 中西文间距 | 自动加空格（盘古之白） | `typo.panhu` + CSS `text-autospace` |
| 避头尾 | `line-break: strict` + 标点悬挂 | `base_css.py` |
| 日期格式 | 统一 `YYYY-MM – 至今` | `typo.normalize_date` |
| 分隔符 | ` · ` | `typo.join_contact` |
| 分页 | 三级防线（见 §10） | `base_css.py` + `pdf_worker.py` |

---

## 10. 分页实现现状（三级防线）

**第一级 CSS**（`engine/base_css.py`，已实现）：
`.rsec{break-inside:avoid}`、`.rsec-title{break-after:avoid-page}`、`.ritem{break-inside:avoid}`、`p,li{orphans:3;widows:3}`、`.r-pagebreak:last-child{break-before:auto}`、`.r-pagebreak + .rsec{margin-top:0}`、`.rsec:has(+ .r-pagebreak){margin-bottom:0}`。

**第二级 JS 测量**（`pdf_worker.py measure`，已实现）：`emulate_media('print')` → 等 `document.fonts` → 测每个 `.rsec` 的 top/height → 页数、跨页区块、建议分页点（起始在页面底部 12% 内且不超一页）、警告（超一页 / 末页内容过少）。

**第三级手动分页**（后端已支持，前端 UI 待写）：`doc.pageBreaks` → 渲染时注入 `.r-pagebreak`。

---

## 11. 运行与测试

```bash
cd E:\pythonProject\resume-builder
$env:PYTHONPATH = 'E:\pythonProject\resume-builder'   # 必须，否则 ModuleNotFoundError

python app.py                        # 启动（前端写好后 http://localhost:5000）
python tests\api_e2e.py              # 端到端 API 测试（当前 39/41，2 个预期失败）
python tests\smoke_render.py         # 6 模板 × 2 示例渲染
python tests\smoke_pdf.py            # PDF 管线（真实起 Chromium，较慢）
python tests\debug_outline.py        # CFF vs glyf 字体嵌入对照（解决 §4 用）
python tests\debug_fonts.py          # document.fonts 加载状态
python tests\debug_pdf_fonts.py      # PDF 内嵌字体原始信息 + 渲染页面图
```

### ⚠️ 环境坑（都踩过）

1. **跑 Python 必须设 `PYTHONPATH`**（或在项目根执行），否则 `ModuleNotFoundError: No module named 'resume_builder'`。
2. **PowerShell 里不要用多行 `python -c "..."`**（引号/转义会炸）——写成 .py 文件再跑。
3. **`page.pdf()` 不接受 BytesIO**，必须传文件路径再读回。
4. **`C:\Windows\Fonts` 枚举被 ACL 挡回**（Get-ChildItem 返回 0 条），但按字体名引用正常。
5. **端口 5000**：旧服务已停、端口已释放，可直接启动。
6. **字体转换很慢**：31k 字形 otf2ttf 前台跑会超时，用后台任务。
7. **`tests/api_e2e.py` 会写 `data/resumes.db` 和导入模板目录**——测试结尾已自清理（白名单式），但异常中断可能残留，届时手动删。

---

## 12. 其他备注

- `docs/SPEC.md` 是完整规格，与代码现状基本一致，**以代码为准**。
- `legacy/editor_v1.js` 的 `buildResumeFromPDF()` 已移植到 `services/pdf_import.py`。
- 调研阶段子代理曾留下 31 个 `evil*` 模板目录（zip 穿越测试产物），**已清理**；`_fonttest` 已移至 `docs/research/cn-typography-fonts/`。
- 中文字体为 Noto Sans SC / Noto Serif SC，**SIL OFL 1.1 许可**，可自由使用嵌入再分发。
- 旧版 `/api/export-html-pdf` 端点**未迁移**（v1 用前端改过的 HTML 直出 PDF）。新架构下前端改 HTML 再回传的场景已被 `/api/v1/render` + `pageBreaks` 覆盖，如确需保留再加。
