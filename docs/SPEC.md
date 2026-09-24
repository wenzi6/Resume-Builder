# Resume Studio 重构规格说明书

> 版本：v2.0 ｜ 状态：Phase 1 实施中
> 依据：4 路联网调研（顶级产品对标 / ATS 规则 / 中文排版规范 / Chromium 分页技术），详见 `docs/research/`

---

## 1. 目标

把一个"能用的简历生成脚本"重构为**长期使用的简历产品**，以**排版完美**为第一优先级。

- **Phase 1（排版）**：设计令牌化的模板引擎、6 套设计级模板、中文字体嵌入、无孤行/无截断/无空白页的 PDF 管线、全新编辑器
- **Phase 2（产品化）**：多简历管理（SQLite）、JD 关键词匹配与 ATS 检查、LLM 内容润色（用户提供 key）

## 2. 技术栈

Python 3.12 + Flask 3 + Jinja2 + Playwright（PDF）+ python-docx（Word）+ SQLite（Phase 2）。
前端：原生 ES Modules 组件化，**无构建步骤**（双击 `python app.py` 即用）。

## 3. 架构

```
resume-builder/
├── app.py                        # 入口（保持兼容：python app.py）
├── requirements.txt
├── resume_builder/
│   ├── __init__.py               # create_app()
│   ├── config.py                 # 路径与运行配置
│   ├── schema.py                 # 简历数据 schema、校验、默认值、旧版迁移
│   ├── registry.py               # 内置区块注册表（类型化定义）
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── tokens.py             # 设计令牌 → CSS 变量
│   │   ├── typo.py               # 中文排版工具（盘古之白/日期/标点/避头尾）
│   │   ├── renderer.py           # Jinja2 渲染 + 分页 CSS 注入
│   │   ├── pagination.py         # 分页测量（Playwright print 媒体）
│   │   └── pdf.py                # PDF 渲染子进程封装
│   ├── exporters/
│   │   ├── __init__.py
│   │   ├── pdf.py                # PDF 导出
│   │   ├── docx.py               # Word 导出（重写）
│   │   └── json_io.py            # JSON 导入导出
│   ├── services/
│   │   ├── documents.py          # 简历文档 CRUD（SQLite，Phase 2）
│   │   ├── analyze.py            # JD 关键词 / ATS 检查（Phase 2）
│   │   └── llm.py                # LLM 润色（Phase 2）
│   └── api/                      # Flask Blueprint（/api/v1/*）
├── templates/                    # 新模板体系
│   └── <id>/
│       ├── template.json         # 元信息 + 版式族 + 默认设计参数
│       ├── layout.html           # Jinja2 布局
│       ├── layout.css            # 版式样式（消费 CSS 变量）
│       └── preview.png           # 模板预览图
├── static/
│   ├── editor.html / editor.css
│   └── js/                       # ES Modules 组件
├── fonts/                        # Noto Sans SC / Noto Serif SC 静态 OTF（OFL）
├── data/                         # SQLite + 示例数据
├── docs/
│   ├── SPEC.md                   # 本文档
│   └── research/                 # 调研原始产出
└── tests/
```

## 4. 数据模型

```python
Document = {
  "id": "uuid",
  "title": "前端工程师-张三",
  "templateId": "modern",
  "design": {                    # 设计参数（覆盖模板默认值）
    "fontFamily": "sans",        # sans | serif
    "fontScale": 1.0,            # 0.9 ~ 1.15，全局字号缩放
    "lineHeight": 1.45,          # 1.2 ~ 1.8
    "sectionGap": 18,            # px，区块间距
    "pageMargin": 20,            # mm，页边距（硬下限 12.7mm = 0.5in）
    "accent": "#0f766e",         # 主题色
    "dateAlign": "right",        # right | below
    "showPhoto": false,          # 照片占位（默认关，ATS 友好）
    "compact": false             # 一键压缩到一页
  },
  "sections": [ SectionConfig ], # 顺序即渲染顺序
  "content": { ... }             # 各区块数据
}

SectionConfig = {
  "key": "workExperiences",
  "title": "工作经历",
  "type": "object|array|simple|skills",
  "fields": [ FieldDef ],
  "visible": true
}
FieldDef = { "key": "company", "label": "公司", "type": "text|date|textarea|list|rating" }
```

**内置区块**：`profile`(object) / `summary`(simple) / `workExperiences`(array) / `projects`(array) / `educations`(array) / `skills`(skills) / `selfEvaluation`(simple) / `custom`(simple)。
用户可新增任意自定义区块（继承通用渲染器）。

**旧数据迁移**：`schema.migrate_legacy()` 把 v1 的 `_sections` + 扁平 content 转为新模型，保证历史 JSON 可直接导入。

## 5. 排版规范（Phase 1 核心）

### 5.1 设计令牌（默认值，来源于调研对标）

| 令牌 | 默认 | 范围 | 说明 |
|---|---|---|---|
| 正文字号 | 10.5pt | 9–12pt | `fontScale` 联动 |
| 行距 | 1.45 | 1.2–1.8 | |
| 区块间距 | 18px | 8–32px | |
| 页边距 | 20mm | 12.7–25mm | 硬下限 0.5in |
| 姓名 | 17pt bold | | 全文最大 |
| 区块标题 | 12.5pt bold | | 带主题色装饰 |
| 条目标题 | 11pt semibold | | |
| 日期 | 右对齐 | right/below | 可切换 |
| 每行字数 | 35–45 字 | | 由栏宽与字号自然约束 |

### 5.2 中文排版规则（`engine/typo.py` + 基础 CSS）

1. **盘古之白**：中西文之间、中文与数字之间自动插入空格（渲染期 Jinja filter + CSS `text-autospace` 双保险）
2. **日期格式**：统一 `YYYY-MM`，`至今` 用全角破折号区间 `2021-03 – 至今`
3. **分隔符**：信息栏统一 ` · `，全篇一致
4. **避头尾**：点号/后括号不出现在行首（`line-break: strict` + 标点挤压）
5. **标点悬挂**：行尾标点悬挂 1/2 字宽（`hanging-punctuation`，优雅降级）
6. **字体层级**：默认黑体（Noto Sans SC）标题+正文；`serif` 档切换 Noto Serif SC，用于正式岗位

### 5.3 字体管线（调研实证结论）

- `fonts/` 仅放**静态 OTF**；可变字体（`NotoSansSC-VF.ttf`）会被 Chromium 降级为 Type3，**禁用**
- `@font-face` 用相对路径 + `file://` 打开 → 实测可用，Chromium 自动子集化（17MB 字体 → PDF 内约 0.6MB/子集）
- PDF 生成后用 pymupdf 校验字体为 Type0 子集（非 Type3），作为回归测试

### 5.4 完美分页（三级防线）

**第一级：CSS 规则**（`engine/print.css`，所有模板共享）

```css
/* 区块整体不拆分（限高场景） */
.rsec { break-inside: avoid; }
/* 标题不与正文分离 */
.rsec-title { break-after: avoid-page; }
/* 条目不拆分 */
.ritem { break-inside: avoid; }
/* 孤行寡行控制 */
p, li { orphans: 3; widows: 3; }
/* 末元素防空白页 */
.page-break:last-child { break-before: auto; }
/* flex/grid 内分页属性失效 → 布局容器不用 flex/grid 承载分页单元 */
```

**第二级：JS 测量**（`engine/pagination.py`）

`page.emulate_media('print')` → `document.fonts.ready` → 测量每个 `.rsec` 的 `offsetTop/offsetHeight` → 结合 A4 内容高度（1122.5px − 上下边距）计算分页点 → 返回 `{pageCount, safeBreaks}`；超出一页的元素标记为"需拆分"。编辑器据此显示真实页数与分页线。

**第三级：手动分页**（编辑器「分页」模式）

用户在预览中拖动分页线 → 生成 `doc.pageBreaks = [{beforeSectionKey: "..."}]` → 渲染时在对应锚点注入 `.page-break`。导出走同一份 HTML，预览即所得。

**Playwright 参数**：`prefer_css_page_size=True` + `print_background=True` + 显式 `format="A4"`，margin 与 `@page` 二选一（统一用 CSS `@page`）。

### 5.5 空白页规避清单

1. 末元素 `break-before: page` → `:last-child { break-before: auto }`
2. `html/body { height: 100% }` → 禁用
3. 底部 margin/padding 溢出 → 打印样式统一清零
4. `break-inside: avoid` 元素高于一页 → 允许拆分（不限高）
5. margin collapse 导致边界偏移 → 用 padding 隔离

## 6. 模板体系

每个模板声明**版式族**，共享同一套区块渲染与令牌：

| 模板 | 版式族 | 定位 |
|---|---|---|
| `classic` | 单栏通排 | ATS 友好默认，中文正式 |
| `modern` | 左侧边栏（38%） | 现代，主题色侧栏 |
| `minimal` | 单栏 + 细线分隔 | 极简，大量留白 |
| `professional` | 单栏衬线 | 正式/学术/国企 |
| `tech` | 深色头部 band + 单栏 | 技术岗（qmjianli 升级） |
| `ats-plain` | 单栏纯文本 | 零装饰，仅标准字体与黑色文字 |

`template.json`：

```json
{
  "id": "modern",
  "name": "现代双栏",
  "description": "...",
  "layout": "sidebar-left",
  "atsSafe": false,
  "defaultDesign": { "accent": "#0f766e", "fontFamily": "sans" },
  "supportedDesign": ["accent", "fontFamily", "fontScale", "lineHeight", "sectionGap", "pageMargin", "dateAlign"]
}
```

## 7. API（`/api/v1`）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/v1/templates` | GET | 模板列表（含默认设计参数） |
| `/api/v1/schema/sections` | GET | 区块定义（驱动表单渲染） |
| `/api/v1/documents` | GET/POST | 列表 / 新建 |
| `/api/v1/documents/<id>` | GET/PUT/DELETE | 读写 |
| `/api/v1/documents/<id>/duplicate` | POST | 复制 |
| `/api/v1/render` | POST | `{templateId, design, content}` → HTML |
| `/api/v1/page-info` | POST | 测量页数与分页点 |
| `/api/v1/documents/<id>/export/<fmt>` | GET | pdf / docx / json |
| `/api/v1/import/json` | POST | JSON 导入（含 v1 迁移） |
| `/api/v1/import/pdf` | POST | PDF 解析（Phase 2 增强） |
| `/api/v1/import/template` | POST | 模板导入（.html/.zip） |
| `/api/v1/analyze` | POST | JD 关键词匹配（Phase 2） |
| `/api/v1/llm/polish` | POST | LLM 润色（Phase 2） |

旧 `/api/*` 端点保留为兼容层，重定向到 v1 实现。

## 8. 前端编辑器

```
static/js/
├── app.js               # 启动、路由、全局事件
├── store.js             # 状态 + 防抖自动保存（后端 + localStorage 双写）
├── api.js               # fetch 封装
├── components/
│   ├── sidebar.js       # 文档列表（Phase 2）+ 区块树（排序/显隐/重命名/新增/删除）
│   ├── form.js          # schema 驱动的表单渲染器（含条目增删/上下移）
│   ├── designPanel.js   # 设计参数面板（字体/字号/行距/间距/边距/主题色/日期对齐）
│   ├── preview.js       # iframe 预览 + 防抖刷新 + 页码指示
│   ├── pagination.js    # 分页编辑模式（拖拽分页线）
│   ├── jsonEditor.js    # JSON 编辑
│   └── toast.js         # 通知
```

交互基线：编辑即预览（300ms 防抖）、区块拖拽排序、`Ctrl+S` 保存、导出前页数提示。

## 9. 质量门禁

- `pytest tests/` 全绿
- 字体回归：导出 PDF 中断言字体为 Type0 子集且中文可检索
- 分页回归：构造 1/2/3 页内容，断言页数正确、无空白页、区块标题不落在页底
- ATS 回归：`ats-plain` 模板导出的 DOCX/PDF 可被 pdfplumber 提取出完整文本

## 10. 实施顺序

1. 字体下载与校验 ✅
2. 后端包骨架（schema / registry / engine / exporters / api）
3. 6 套模板
4. 前端编辑器
5. 测试与视觉走查
6. Phase 2：SQLite 多文档 / JD 匹配 / LLM
