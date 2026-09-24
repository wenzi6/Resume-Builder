# Resume Studio · 简历工作室

把「能用的简历脚本」升级为**长期使用的简历产品**：排版完美的模板引擎 + 可视化编辑器 + PDF/Word/JSON 导出 + 本地持久化。

**第一优先级是排版完美**——中文字体正确嵌入（Type0 子集、文本可检索）、完美分页（无孤行 / 无截断 / 无空白页）、ATS 友好。

```bash
cd E:\pythonProject\resume-builder
$env:PYTHONPATH = 'E:\pythonProject\resume-builder'   # Windows PowerShell 必须设置
python app.py
# 打开 http://localhost:5000
```

> 双击 `python app.py` 即用：无需构建步骤、无需数据库配置、无外部服务依赖（LLM 功能为用户自选 Phase 2）。
> 唯一的前置依赖是 Playwright 的 Chromium（首次使用执行一次 `playwright install chromium`）。

---

## 功能一览

### 编辑器（`static/`，原生 ES Modules，无构建）

| 区域 | 能力 |
|---|---|
| 顶栏 | 简历重命名、模板切换（6 套，含 ATS 徽章）、导入、JSON 编辑、导出 PDF / Word / JSON |
| 左栏 · 区块 | 区块树：拖拽 / 箭头排序、显隐切换、重命名、删除；内置 7 区块 + 自定义区块（列表型 / 单块型，字段可配） |
| 左栏 · 设计 | 字体（黑体 / 宋体 / **上传自有字体**）、字号缩放、行距、区块间距、页边距、主题色（预设 + 取色器）、日期位置、照片开关、一键压缩到一页、**⚡ 自动适应一页**（迭代压缩直到排进一页） |
| 左栏 · 简历 | 多简历管理：新建（示例 / 空白）、切换、复制、删除、**历史版本**（自动快照，可恢复） |
| 中栏 | schema 驱动的表单：文本 / 日期 / 多行 / 列表（增删上下移）/ 技能星级，条目卡片增删排序 |
| 右栏 | iframe 实时预览（300ms 防抖）、页码指示与警告、缩放、**分页编辑模式** |

**编辑即所见**：表单变更 → 防抖 300ms 重新渲染 → 800ms 自动保存（后端 + localStorage 双写，刷新可恢复）。`Ctrl+S` 立即保存，`Ctrl+E` 导出 PDF，`Ctrl+Z` / `Ctrl+Y` 撤销 / 重做（以编辑突发为粒度）。

**分页编辑模式**：测量每个区块的落位，在预览中画出虚线分页线（位置按打印坐标精确反算，手动分页点也算在内）；点区块右上角「在此分页」写入手动分页点；「应用建议分页」一键采用后端建议（起始位置落在页面底部 12% 内的区块）。

### 模板体系（6 套）

| id | 名称 | 版式 | ATS | 说明 |
|---|---|---|---|---|
| `classic` | 经典通排 | 单栏 | ✅ | 居中页眉 + 通栏细线标题，最通用 |
| `modern` | 现代双栏 | 左侧边栏 | ❌ | 渐变通栏页眉 + 33% 边栏 |
| `minimal` | 极简 | 单栏 | ✅ | 细线分隔、大字距标题、大量留白 |
| `professional` | 专业衬线 | 单栏 | ✅ | 宋体正文 + 双线标题，正式稳重 |
| `tech` | 技术深色 | 深色页眉 | ❌ | 渐变页眉 + 左侧时间轴 + 等宽日期 |
| `ats-plain` | ATS 纯文本 | 单栏 | ✅ | 零颜色零背景零图标，评分条隐藏 |

每套模板 = `template.json`（元信息 + slot 分配 + 默认设计参数）+ `layout.html`（Jinja2 布局）+ `layout.css`（视觉）。**所有模板共享同一套区块 HTML 语义标记**，视觉差异只由模板 CSS 决定——新增模板只需建目录放这三个文件，自动扫描。

### 排版引擎

- **设计令牌**：`doc.design`（字体 / 字号 / 行距 / 间距 / 边距 / 主题色…）由 `engine/tokens.py` 编译为 CSS 变量，模板只消费变量；`compact` 一键联动四参数
- **中文排版**：盘古之白（中西文自动空格）、日期归一化（`YYYY-MM – 至今`）、统一 ` · ` 分隔符、避头尾（`line-break: strict`）、标点悬挂
- **完美分页三级防线**：① CSS 规则（区块 / 条目不拆分、标题不分离、孤行寡行控制、防空白页）② Playwright 测量（页数、区块落位、建议分页点、警告）③ 手动分页（`doc.pageBreaks` → 渲染注入 `.r-pagebreak`）
- **字体管线**：Noto Sans/Serif SC 嵌入 PDF，Chromium 自动子集化（17MB → 约 0.6MB）

### 导入导出

- **导出**：PDF（Playwright + `@page` A4）、Word（python-docx，字号 / 行距 / 边距与 HTML 一致）、JSON（含信封格式）、**自包含 HTML**（字体 base64 内嵌，离线可开）
- **导出质量自检**：每次导出 PDF 后校验内嵌字体——发现 Type3 降级（用户导入的模板引用了不可嵌入的字体）会通过响应头返回警告，编辑器即时提示
- **导入**：JSON（兼容 v1 旧格式，自动迁移，换发新 id 不覆盖已有简历）、PDF（pdfplumber 解析为结构化文档）、模板（.html / .zip，含路径穿越防护）
- **自有字体**：上传 .ttf / .otf → 自动检测 CFF 并转换为 glyf + 剥离部首 cmap → 注册进设计面板，PDF 导出时正常嵌入为 Type0
- **持久化**：SQLite（WAL 模式）多简历管理 + 每份文档最近 20 份历史快照（`data/resumes.db`，运行时自动生成）

---

## 架构

```
app.py                        # 入口：python app.py
pdf_worker.py                 # Playwright 子进程：pdf / measure 两种模式
resume_builder/
├── __init__.py               # create_app() + main()
├── config.py                 # 路径 / 端口 / 边距下限 / 允许的跨域源
├── schema.py                 # Document 模型、归一化、v1→v2 迁移
├── registry.py               # 内置区块注册表（7 区块）★单一事实来源
├── sample.py                 # 两份示例数据
├── engine/
│   ├── tokens.py             # 设计参数→CSS 变量、@font-face（内置+用户字体）、@page  ★字体清单在此
│   ├── font_convert.py       # CFF→glyf 转换 + 部首 cmap 剥离（tools 的 CLI 是其封装）
│   ├── typo.py               # 盘古之白 / 日期归一化 / 分隔符（Jinja filters）
│   ├── base_css.py           # 共享基础样式 + 打印分页规则
│   ├── sections.py           # 区块 → 规范化 HTML（.rsec/.ritem/.rlist 语义标记）
│   ├── renderer.py           # Jinja2 渲染 + slot 分配 + 分页锚点
│   └── pdf.py                # 子进程封装 + 分页测量 + 字体校验 + 临时文件清理
├── exporters/
│   ├── docx.py               # Word 导出
│   ├── html_export.py        # 自包含 HTML（字体 base64 内嵌）
│   └── json_io.py            # JSON 导入导出（含 v1 迁移）
├── services/
│   ├── documents.py          # SQLite 持久化（WAL + 版本快照）
│   ├── font_manager.py       # 用户自有字体：转换 + 清洗 + 注册
│   ├── autofit.py            # 一键适应一页（迭代压缩）
│   └── pdf_import.py         # PDF → 结构化文档
└── api/                      # /api/v1/* Blueprint + /api/* 旧版兼容层
templates/                    # 6 套模板（template.json + layout.html + layout.css）
static/                       # 前端编辑器（editor.html / editor.css / js/ ES Modules，含 i18n）
fonts/                        # Noto Sans/Serif SC 静态 TTF（OFL 许可）+ user/ 用户上传
tests/                        # pytest 套件（108 用例）
tools/                        # 字体维护工具（otf2ttf / strip_radical_cmap）
legacy/                       # v1 全部源码归档（不参与运行，未纳入 git）
```

### 数据模型

```python
Document = {
  "id": "uuid hex", "title": str, "templateId": str,
  "design": {...},                  # 字体/字号/行距/间距/边距/主题色/日期位置/照片/压缩
  "sections": [ SectionConfig ],    # 顺序即渲染顺序
  "content": {...},                 # 各区块数据
  "pageBreaks": [sectionKey, ...],  # 手动分页点
  "version": 2, "createdAt": float, "updatedAt": float,
}
SectionConfig = {"key","title","type":"object|array|simple|skills","fields":[FieldDef],"visible":bool}
```

内置区块：`profile`(object) / `workExperiences`(array) / `projects`(array) / `educations`(array) / `skills`(skills) / `selfEvaluation`(simple) / `custom`(simple)。用户可新增自定义区块。

### API（`/api/v1`）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/v1/templates` | GET | 模板列表（含 defaultDesign） |
| `/api/v1/schema/sections` | GET | 区块定义，驱动表单渲染 ★单一事实来源 |
| `/api/v1/documents` | GET/POST | 列表 / 新建 |
| `/api/v1/documents/from-sample/<general\|tech>` | POST | 从内置示例创建 |
| `/api/v1/documents/<id>` | GET/PUT/DELETE | 读写删 |
| `/api/v1/documents/<id>/duplicate` | POST | 复制 |
| `/api/v1/render` | POST | `{document}` → 预览 HTML |
| `/api/v1/page-info` | POST | 页数 + 区块落位 + 建议分页点 + 警告（含手动分页点换算） |
| `/api/v1/auto-pagebreaks` | POST | 只返回建议分页点 |
| `/api/v1/auto-fit` | POST | 一键适应一页：迭代压缩直到页数 ≤ 1 |
| `/api/v1/fonts` | GET | 用户自有字体列表 |
| `/api/v1/fonts/upload` | POST | 上传字体（自动转换 + 清洗 + 注册） |
| `/api/v1/fonts/<file>` | DELETE | 删除用户字体 |
| `/api/v1/documents/<id>/versions` | GET | 文档历史快照 |
| `/api/v1/documents/<id>/versions/<vid>/restore` | POST | 恢复历史版本 |
| `/api/v1/export/{pdf,docx,json,html}` | POST | 导出（支持 `{id}` 或 `{document}`） |
| `/api/v1/import/json` | POST | JSON 导入（含 v1 迁移，换发新 id） |
| `/api/v1/import/pdf` | POST | PDF 解析成结构化文档 |
| `/api/v1/import-template` | POST | 模板导入（.html/.zip，有穿越防护） |

旧版 `/api/*` 兼容层：`/api/templates`、`/api/sample-data`、`/api/preview/<t>`、`/api/render/<t>`、`/api/export-pdf/<t>`、`/api/export-word/<t>` 已桥接。其他路由：`GET /`（编辑器）、`GET /static/<file>`、`GET /fonts/<file>`、`GET /data/<file>`、`GET /healthz`。

---

## 字体管线（重要背景）

Chromium 的 PDF 后端**无法正确嵌入 CFF 轮廓的 web font**，会降级为 Type3（文本层乱码、ATS 无法解析）；只有 glyf 轮廓才能嵌入为 Type0 子集。因此：

1. `fonts/` 只放 **glyf TTF**（当初下载的 Noto OTF 已用 `tools/otf2ttf.py` 一次性转换，`.otf` 已删除）
2. Noto CJK 字体的 cmap 中，208 个康熙部首（U+2F00–U+2FDF）与汉字**共用字形**，Chromium 构建 ToUnicode 时按字形反查会命中部首码位（如 ⾼ U+2FBC 而不是 高 U+9AD8），导致 pdfplumber/pdfminer 提取乱码。已用 `tools/strip_radical_cmap.py` 剥离（pymupdf 不受影响，但 ATS 解析常用 pdfplumber）
3. 等宽字体栈必须指向可嵌入的字体（`"Consolas", "Courier New", "Noto Sans SC", monospace`）——`ui-monospace` / `Cascadia Mono` / 通用 `monospace` 回退会产生 Type3

修改字体相关代码后务必跑 `pytest tests/test_pdf_fonts.py`（字体回归）。

---

## 开发

```bash
$env:PYTHONPATH = 'E:\pythonProject\resume-builder'

python app.py                        # 启动（http://localhost:5000）
python -m pytest tests/ -q           # 全部测试（108 用例，PDF 用例会真实起 Chromium）
python tests/debug_pdf_fonts.py      # 诊断：PDF 内嵌字体原始信息 + 渲染页面图
```

测试套件构成：

| 文件 | 覆盖 |
|---|---|
| `test_api.py` | 全部 API 端点、CRUD、导入（含 v1 迁移）、模板导入穿越防护、旧版兼容层、边界情况 |
| `test_render.py` | 6 模板 × 2 示例渲染、语义标记完整性、设计令牌编译 |
| `test_pdf_fonts.py` | **P0 字体回归**：Type0 子集 + 中文可检索 + file:// 路径 + 目录无 OTF |
| `test_pagination.py` | 1/2/3 页页数、无空白页、手动分页换算、标题不落页底 |
| `test_ats.py` | ats-plain 的 PDF（pymupdf + pdfplumber 双库）/ DOCX 文本完整提取 |
| `test_import_pdf.py` | PDF 导入：自家管线生成样本 → 解析回结构化数据 → 坏文件优雅失败 |
| `test_visual_regression.py` | 视觉回归：6 模板位图与基线像素对比（`REGEN_BASELINES=1` 更新基线） |
| `test_features.py` | 字体上传 / 自动适应 / HTML 导出 / 版本历史 / 导出字体自检 / photo 安全 |

### 环境坑（都踩过）

1. **跑 Python 必须设 `PYTHONPATH`**（或在项目根执行），否则 `ModuleNotFoundError: No module named 'resume_builder'`
2. PowerShell 里不要用多行 `python -c "..."`（引号 / 转义会炸）——写成 .py 文件再跑
3. `page.pdf()` 不接受 BytesIO，必须传文件路径再读回
4. 重启开发服务器前确认端口 5000 已释放（`netstat -ano | findstr :5000`）
5. 字体转换很慢（31k 字形），必须放后台跑

---

## 路线图

**Phase 1（排版）——已完成**：令牌化模板引擎、6 套模板、中文字体嵌入、完美分页、可视化编辑器、测试套件。

**Phase 2（产品化）——待办**：

1. **JD 关键词匹配 / ATS 检查**：输入 JD 文本 → 提取关键词（硬技能 > 教育 > 职位 > 软技能）→ 与简历比对 → 匹配率 + 缺失建议（纯本地实现，阈值 ≥75%）
2. **LLM 内容润色**：OpenAI 兼容协议（base_url / api_key / model 用户可配，key 不提交）；bullet 按 Google XYZ 公式润色、按 JD 定制改写、量化成果建议
3. 模板预览图（每套一张 `preview.png`）
4. 多文档管理 UI 增强（后端已就绪）

---

## 许可

代码：MIT。字体：[Noto Sans/Serif SC](https://github.com/notofonts/noto-cjk)，SIL OFL 1.1。
