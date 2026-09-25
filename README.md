# Resume Studio · 简历工作室

> 把「能用的简历脚本」升级为**长期使用的简历产品**。
> 排版完美的模板引擎 + 可视化编辑器 + AI 助手 + PDF/Word/JSON 导出 + 本地持久化。

[![Tests](https://github.com/wenzi6/Resume-Builder/actions/workflows/ci.yml/badge.svg)](https://github.com/wenzi6/Resume-Builder/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**第一优先级是排版完美**：中文字体正确嵌入（Type0 子集、文本可检索）、页数与所见即所得、无孤行 / 无截断 / 无空白页、ATS 友好。

---

## 目录

- [一、快速开始](#一快速开始)
- [二、使用说明书](#二使用说明书)
  - [2.1 五分钟制作第一份简历](#21-五分钟制作第一份简历)
  - [2.2 区块编辑](#22-区块编辑)
  - [2.3 模板与设计](#23-模板与设计)
  - [2.4 分页：让内容正好一页](#24-分页让内容正好一页)
  - [2.5 导入现有简历](#25-导入现有简历)
  - [2.6 导出](#26-导出)
  - [2.7 ✨ AI 助手](#27--ai-助手)
  - [2.8 多简历与数据安全](#28-多简历与数据安全)
- [三、配置说明](#三配置说明)
- [四、技术架构](#四技术架构)
- [五、开发指南](#五开发指南)
- [六、常见问题](#六常见问题)

---

## 一、快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.10+（推荐 3.12） | |
| Playwright Chromium | 最新 | PDF 渲染引擎，**必须安装** |
| 操作系统 | Windows / macOS / Linux | 开发与测试基于 Windows |

### 安装（三步）

```bash
# 1. 克隆仓库
git clone https://github.com/wenzi6/Resume-Builder.git
cd Resume-Builder

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 Chromium（PDF 渲染用，一次性）
python -m playwright install chromium
```

### 启动

```bash
python app.py
```

打开浏览器访问 **http://localhost:5000** ，即可开始使用。

> **Windows 用户注意**：如果在项目根目录外启动遇到 `ModuleNotFoundError`，请先设置
> `$env:PYTHONPATH = 'E:\path\to\Resume-Builder'`（PowerShell）。

**就这样**——无需数据库配置、无需构建步骤、无需注册账号。所有数据在本机 `data/` 目录。

---

## 二、使用说明书

### 2.1 五分钟制作第一份简历

1. **启动后自动创建**一份示例简历（可直接改）
2. **中栏表单**：逐项填写个人信息、工作经历、项目、教育、技能
3. **右栏预览**：实时看到排版效果（输入后 300ms 自动刷新）
4. **顶栏「导出 PDF」**：获得可投递的文本型 PDF（ATS 可解析）

**快捷键**

| 快捷键 | 功能 |
|---|---|
| `Ctrl+S` | 立即保存 |
| `Ctrl+E` | 导出 PDF |
| `Ctrl+Z` / `Ctrl+Y` | 撤销 / 重做 |
| `Esc` | 关闭弹窗 |

### 2.2 区块编辑

左栏「**区块**」页签管理简历的组成区块：

| 操作 | 方法 |
|---|---|
| **排序** | 拖拽行，或点 ↑ ↓ 箭头 |
| **显隐** | 点眼睛图标（隐藏的内容保留不丢失） |
| **重命名** | 点 ✎ 图标 |
| **删除** | 点 ✕（可随时从「添加区块」找回内置区块） |
| **添加自定义区块** | 「+ 添加区块」→ 选列表型 / 单块型 → 配置字段 |

内置 7 个区块：个人信息、工作经历、项目经历、教育经历、专业技能、自我评价、其他信息。

**区块排版微调**：点区块标题右侧 ⚙ 图标，可设置**条目双列排列**（适合短条目技能）、**隐藏区块标题**。

### 2.3 模板与设计

**6 套模板**（顶栏切换，带预览图）：

| 模板 | 版式 | ATS 友好 | 适用 |
|---|---|---|---|
| 经典通排 | 单栏 | ✅ | 最通用，正式场合 |
| 现代双栏 | 左侧边栏 | ❌ | 设计感、信息密度高 |
| 极简 | 单栏细线 | ✅ | 留白多、克制 |
| 专业衬线 | 宋体单栏 | ✅ | 国企 / 学术 / 金融 |
| 技术深色 | 深色页眉 | ❌ | 互联网 / 技术岗 |
| ATS 纯文本 | 零装饰 | ✅ | 机器解析成功率最高 |

**设计参数**（左栏「设计」页签，改完即时生效）：

| 参数 | 范围 | 说明 |
|---|---|---|
| 正文字体 | 黑体 / 宋体 / 自有字体 | |
| **标题字体** | 黑体 / 宋体 | 独立于正文，制造层级 |
| 字号缩放 | 80%–115% | 全局等比 |
| 行距 | 1.20–1.80 | |
| 区块间距 | 8–32 px | |
| 页边距 | 12.7–25 mm | 下限 0.5 英寸，保证打印可读 |
| 主题色 | 取色器 + 10 预设 | 自动派生浅色/深色变体 |
| 日期位置 | 右对齐 / 标题下 | |
| 显示照片 | 开 / 关 | ATS 场景建议关闭 |
| 压缩到一页 | 开 / 关 | 一键联动四项参数 |
| **⚡ 自动适应一页** | 按钮 | 自动迭代压缩直到排进一页（或告诉你放不下） |

### 2.4 分页：让内容正好一页

- **页码指示**：右栏顶部实时显示「共 N 页」——与实际导出**永远一致**（以真实渲染为准）
- **分页编辑模式**：点「分页」按钮 →
  - 预览中画出**虚线分页线」（第 N 页 / 第 N+1 页分界）
  - 每个区块右上角出现「**在此分页**」按钮，点击即设 / 取消手动分页
  - 「**应用建议分页**」：自动把起始位置落在页面底部 12% 内的区块提到下一页
  - 「**清除全部分页**」：一键还原
- **超页警告**：内容超过一页 / 末页内容过少时，页码旁会给出提示

### 2.5 导入现有简历

顶栏「**导入**」支持三种来源：

| 类型 | 说明 |
|---|---|
| **PDF 简历** | 解析 PDF 为结构化数据：按「加粗行=公司+日期 / 非加粗短行=职位」的版式规律精确拆分公司与职位，原格式保留 + 模块化编辑 |
| **JSON** | 本工具导出的 JSON，或旧版 v1 格式（自动迁移） |
| **模板** | `.html` 单文件或 `.zip`（layout.html + layout.css + template.json），放即生效 |

### 2.6 导出

| 格式 | 特点 |
|---|---|
| **PDF** | Chromium 渲染，A4，字体子集嵌入，文本可检索（ATS 可解析）；导出时自动做字体质量自检 |
| **Word** | .docx，字号 / 行距 / 边距与网页版一致 |
| **JSON** | 完整数据，可再导入 / 备份 |
| **HTML** | 自包含单文件（字体 base64 内嵌），离线可开，适合分享 / 存档 |

### 2.7 ✨ AI 助手

> 需要**自备 API Key**（OpenAI 兼容协议）。Key 只保存在本机 `data/llm_config.json`，不会上传到任何地方。

**配置（一次搞定）**：点顶栏「✨ AI」→「设置」→

1. 选服务商预设（内置 **24 家**）或自定义
2. 粘贴 API Key → 保存
3. 点「**获取模型**」自动拉取可用模型列表，点击选择（也可手输）
4. 点「测试连接」验证

**支持的 24 家服务商**：

| 类别 | 服务商 |
|---|---|
| 国内 | DeepSeek、智谱 GLM、通义千问、Kimi、火山豆包、MiniMax、腾讯混元、百度千帆、零一万物、阶跃星辰、硅基流动 |
| 海外 | OpenAI、**Anthropic Claude**、**Google Gemini**、**Azure OpenAI**、xAI Grok、OpenRouter、Groq、Together AI、Mistral |
| 本地 / 自建 | Ollama、LM Studio、vLLM、One API / New API 中转 |

自动适配四种 API 协议（OpenAI 兼容 / Anthropic 原生 / Gemini 原生 / Azure），无需关心格式差异。

**五项 AI 能力**：

| 能力 | 说明 |
|---|---|
| **生成简历** | 填目标岗位 / 年限 / 技能 / 经历要点 → 生成结构化简历（不虚构公司名，用占位符） |
| **修改建议** | 通读简历，从量化成果、动词强度、关键词、ATS 友好度给建议（带示例文案） |
| **JD 定制** | 粘贴招聘 JD → 按关键词改写你**已有**的经历（不编造），逐条应用 |
| **JD 匹配** | **纯本地**、离线可用：匹配率 % + 缺失关键词 + 建议（不调用 AI） |
| **对话** | **指挥 AI 改简历**：「把所有工作经历改成 IT 招聘方向」「把公司名改成字节跳动」→ 按真实字段清单生成方案，差异预览、逐条/全部应用、改完自动定位高亮、Ctrl+Z 可撤销 |
| **字段级润色** | 表单里每个多行字段 / 列表行旁的 ✨ 按钮；区块头 ✨ 可**批量润色**整块 |

AI 窗口**可拖拽缩放**（右下角把手，尺寸自动记忆），对话区输入框自适应高度。

**对话改简历工作流**：在「对话」页直接指挥 AI（如「把所有工作经历改成 IT 招聘方向」「把第一段经历的公司名改成字节跳动」「每条 bullet 都补充量化结果」）：

1. **字段清单防瞎编**：对话启动时前端把当前文档的**全部可修改字段路径 + 当前值**交给 AI，AI 只能从清单里选路径，并明确要求「所有/每条」必须逐条枚举——漏改、编造路径的问题从根上消失
2. **差异预览卡片**：每条修改标注人话位置（如「工作经历 #2 · 要点 1」）、当前值 → 新值对照；路径无效的条目标灰注明「路径不存在」而不是静默失败
3. **逐条 / 全部应用**：每条可单独「应用这条」，也可「应用全部」；写入即进入撤销栈，**Ctrl+Z 可回退**
4. **改完自动定位**：应用后表单自动滚动到该字段并绿色闪烁高亮，立即可见；卡片上也有「定位」按钮可随时跳转
5. **思考过程可见**：思考模型（DeepSeek-R1 / QwQ 等）的 reasoning 内容实时流式显示，正文开始后自动折叠为「💭 思考过程（N 字，点击展开）」
6. **截断提示**：方案过长被模型截断时给出可操作提示（拆成多次修改），而不是莫名其妙没反应
7. **上下文随文档切换**：导入新简历或切换到其他简历时，对话自动重置（不会还拿着上一个简历的 JSON 让 AI 分析），各功能页旧结果一并清空；模型配置是全局设置，不随文档重置

**字段级「指哪里改哪里」**：表单每个字段旁的 ✨ 按钮打开润色窗，可在「我的修改要求」里填自定义指令（如「突出量化结果」「改成 IT 招聘方向」），留空则按 Google XYZ 公式自动润色；流式生成、可手动编辑后替换。

### 2.8 多简历与数据安全

左栏「**简历**」页签：

- **多简历管理**：新建（示例 / 空白）、切换、复制、删除、标题搜索
- **历史版本**：每次保存自动快照（最多 20 份），可随时恢复
- **自动备份**：启动时 + 每 30 分钟自动备份数据库（内容无变化则跳过），保留最近 10 份，**可恢复也可删除**
- **导出全部 / 导入全部**：ZIP 打包所有简历（含对照导入的原始 PDF），换机迁移一键完成

---

## 三、配置说明

### AI 配置（`data/llm_config.json`，自动生成）

```json
{
  "base_url": "https://api.deepseek.com",
  "api_key": "sk-...",
  "model": "deepseek-chat",
  "format": "openai",
  "timeout": 90
}
```

`format` 取值：`openai` / `anthropic` / `gemini` / `azure`。选预设时自动带出。

### 设计参数（`doc.design`）

| 字段 | 默认 | 范围 |
|---|---|---|
| `fontFamily` | `sans` | sans / serif / 用户字体家族名 |
| `headFont` | `sans` | sans / serif（标题独立字体） |
| `fontScale` | 1.0 | 0.80–1.15 |
| `lineHeight` | 1.45 | 1.20–1.80 |
| `sectionGap` | 18 | 8–32 px |
| `pageMargin` | 20 | 12.7–25 mm |
| `accent` | `#0f766e` | hex |
| `dateAlign` | `right` | right / below |
| `showPhoto` | false | bool |
| `compact` | false | bool（一键压缩：0.94 / 1.32 / 12px / 15mm） |

---

## 四、技术架构

### 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python 3.12 + Flask | 本地工具，轻量够用 |
| PDF | Playwright + Chromium | 唯一能忠实还原 CSS 排版（flex/grid/渐变）的方案 |
| Word | python-docx | |
| 数据 | SQLite（WAL 模式） | 单机单用户零维护 |
| 前端 | 原生 ES Modules | **无构建步骤**，双击即用 |
| AI | urllib 直连 | 零依赖，支持 4 种协议 |
| 测试 | pytest + Playwright（237 用例） | 含字体 / 分页 / ATS / 视觉回归 |

### 渲染管线

```
normalize_document(doc)                      # schema.py：收敛形状 + v1 迁移
  → render_body_html()                       # sections.py：区块 → 规范化 HTML
      ├─ 每个区块 → .rsec/.ritem/.rlist 语义标记
      └─ pageBreaks 中的 key → 前插 <div class="r-pagebreak">
  → Jinja2 渲染 <template>/layout.html       # 只写结构：top/sidebar/main 三槽位
  → 组装完整 HTML：
      @font-face   预览→/fonts，pdf→file:/// 绝对路径
      @page        { size: A4; margin: <mm> }
      :root        设计令牌 CSS 变量
      base_css     重置 + 语义标记 + 中文排版 + 打印分页规则
      layout.css   模板视觉差异化
```

**核心设计**：所有模板共享同一套区块 HTML 标记，视觉差异**只**由模板 CSS 决定——排版质量一致、打印规则只写一份、自定义区块自动获得全部模板支持。

### 页数为什么永远准确

测量时 Chromium 同时做两件事：JS 原子级分页模拟（复现 `break-inside:avoid` 挪页、双栏独立流）+ **实际渲染 PDF 数页数**。徽章、分页线、「自动适应一页」与最终导出永远一致。

### 目录结构

```
Resume-Builder/
├── app.py                     # 入口：python app.py
├── pdf_worker.py              # Playwright 常驻进程（pdf / measure / pageinfo）
├── requirements.txt
├── resume_builder/
│   ├── __init__.py            # create_app() + main()（waitress 生产模式）
│   ├── config.py              # 路径 / 端口 / 边距下限
│   ├── schema.py              # Document 模型、归一化、v1→v2 迁移
│   ├── registry.py            # 内置区块注册表（7 区块）★单一事实来源
│   ├── sample.py              # 两份示例数据
│   ├── engine/
│   │   ├── tokens.py          # 设计参数 → CSS 变量、@font-face、@page
│   │   ├── font_convert.py    # CFF→glyf 转换 + 部首 cmap 清洗
│   │   ├── base_css.py        # 共享基础样式 + 打印分页规则
│   │   ├── sections.py        # 区块 → 规范化 HTML
│   │   ├── renderer.py        # Jinja2 渲染 + slot 分配
│   │   └── pdf.py             # 常驻 worker 池 + 字体校验 + 备份清理
│   ├── exporters/
│   │   ├── docx.py            # Word 导出
│   │   ├── html_export.py     # 自包含 HTML
│   │   └── json_io.py         # JSON 导入导出（含 v1 迁移）
│   └── services/
│       ├── documents.py       # SQLite 持久化（WAL + 版本快照）
│       ├── bundle.py          # 自动备份 + ZIP 全量导出入
│       ├── font_manager.py    # 用户自有字体管理
│       ├── autofit.py         # 一键适应一页
│       ├── analyze.py         # 本地 JD 关键词匹配
│       ├── llm.py             # AI 客户端（4 种协议 + 流式）
│       ├── pdf_patch.py       # 原格式 PDF 补丁导出
│       ├── pdf_import.py      # PDF → 结构化文档
│       └── source_pdf.py      # 原始 PDF 逐页渲染
│   └── api/                    # /api/v1/* Blueprint（documents/render/export/imports/fonts/llm/analyze/backups）
├── templates/                 # 6 套模板（template.json + layout.html + layout.css + preview.png）
├── static/                    # 前端编辑器（editor.html / editor.css / js/ ES Modules）
├── fonts/                     # Noto Sans/Serif SC（SIL OFL 1.1）+ user/ 用户字体
├── tests/                     # pytest 237 用例 + 视觉回归基线
└── tools/                     # 字体维护 / 预览图生成脚本
```

### API 概览（56 个端点）

| 分组 | 端点 |
|---|---|
| 模板 / Schema | `GET /api/v1/templates`、`GET /api/v1/templates/<id>/preview.png`、`GET /api/v1/schema/sections` |
| 文档 | `GET/POST /api/v1/documents`、`GET/PUT/DELETE /api/v1/documents/<id>`、`POST .../duplicate`、`POST .../from-sample/<n>` |
| 版本 / 备份 | `GET .../versions`、`POST .../versions/<vid>/restore`、`GET/POST/DELETE /api/v1/backups` |
| 渲染 / 分页 | `POST /api/v1/render`、`POST /api/v1/page-info`、`POST /api/v1/auto-pagebreaks`、`POST /api/v1/auto-fit` |
| 导出 / 导入 | `POST /api/v1/export/{pdf,docx,json,html}`、`POST /api/v1/import/{json,pdf}`、`POST /api/v1/import-template`、`GET/POST /api/v1/documents/{export,import}-all` |
| AI | `GET/PUT /api/v1/llm/config`、`POST /api/v1/llm/test`、`GET /api/v1/llm/models`、`POST /api/v1/llm/{polish,polish-batch,generate,suggest,tailor,chat,stream}` |
| 本地分析 | `POST /api/v1/analyze`（JD 匹配，不调用 AI） |
| 字体 | `GET/POST/DELETE /api/v1/fonts`、`POST /api/v1/fonts/upload` |

---

## 五、开发指南

### 运行测试

```bash
python -m pytest tests/ -q        # 237 用例（PDF 用例会真实启动 Chromium，约 2.5 分钟）
node scripts/check_js.mjs         # 前端语法检查（零依赖）
```

测试覆盖：API 全端点 / 6 模板渲染 / **字体回归**（Type0 + 中文可检索）/ **分页回归**（页数一致性）/ **ATS 回归**（pdfplumber 双库提取）/ 视觉回归（位图像素对比）/ AI / 数据安全。

### 新增一套模板

在 `templates/` 下建目录，放三个文件即自动被扫描：

```
templates/mytemplate/
├── template.json     # { "name": "...", "layout": "single|sidebar-left|...", "slots": {...} }
├── layout.html       # Jinja2 布局，用 top_sections / sidebar_sections / main_sections 槽位
└── layout.css        # 只写视觉差异化（消费 --r-* CSS 变量）
```

### 新增字体

把 `.ttf`（或 `.otf`，会自动转换为可嵌入的 glyf 格式）放入 `fonts/`，或在编辑器「设计 → 字体」中上传。修改字体后务必跑 `pytest tests/test_pdf_fonts.py`。

### 新增 AI 服务商

在 `services/llm.py` 的 `PROVIDER_PRESETS` 加一条预设；若是全新 API 协议，在 `_FORMATS` 注册一组 `build_request` / `parse_response` / `parse_delta` 函数。

---

## 六、常见问题

**Q：导出的 PDF 文字能复制吗？能被招聘网站解析吗？**
A：能。PDF 内嵌 Type0 字体子集，文本层完整可检索，ATS 友好（推荐 `classic` / `ats-plain` 模板）。

**Q：页数显示和实际导出不一致？**
A：不会。页数以真实渲染的 PDF 为准，这是回归测试锁定的核心契约。

**Q：AI 配置保存不了 / 下次打开要重填？**
A：不会。配置字段**变更即自动保存**（800ms 防抖，与编辑器一致），重启不丢失。只填 Base URL + Key 也会先保存，启动 AI 功能时若还缺「模型名称」会明确提示缺什么。

**Q：PDF 导入后公司名和职位串行了？**
A：已修复。导入按版式规律判别：加粗行是「公司+日期」，紧随的非加粗短行是职位；职位词结尾的行（工程师/专员/经理…）不会再被误判成公司，公司后缀（有限公司/公司/集团…）优先判公司。修改后原格式导出会把改动精确打进原始 PDF 对应位置（逐字 Span 的 PDF 也能定位）。

**Q：原格式导出后，改动的字看起来和原文字体不一样？**
A：已修复。原文若是 Type3 逐字字体（无法按字体名匹配），补丁会按**墨迹密度**判定原文粗细——比内置 Regular 重的用 Bold，反之用 Regular；插入文字统一用内置 Noto Sans SC（与模板排版同一套黑体），颜色、字号沿用原 Span。纯中文行只重绘变化部分，同行其他内容（如日期）保持原字形。

**Q：之前导入的文档还是老数据（解析不对）？**
A：在左侧「简历」列表里，带「原PDF」标记的文档右侧有 **↻ 重新解析** 按钮（「原始格式」视图的工具条上也有）：用最新解析规则重跑一遍原始 PDF，字段立即刷新，不用删了重导。重新解析前会自动备份一次，原始 PDF 本身不变。

**Q：能保存多套模型配置吗？**
A：能。设置页顶部有配置管理：下拉切换、**＋ 新建**、删除；「配置名称」可自定义（如「DeepSeek 主力」「公司 GPT」「本地 Ollama」），名称同样自动保存。多套配置存于 `data/llm_configs.json`，当前使用哪套一目了然，删到只剩一套时会拒绝删除（至少保留一套）。

**Q：AI Key 安全吗？**
A：Key 只存本机 `data/llm_config.json`（已被 .gitignore），除你选择的服务商外不发往任何地方；接口不返回 Key 本身。

**Q：想换电脑？**
A：「简历」页签 →「导出全部」得到 ZIP，在新电脑导入全部即可（含原始 PDF）。

**Q：支持哪些浏览器？**
A：Chrome / Edge 等现代浏览器（PDF 渲染基于 Chromium）。

**Q：字体版权？**
A：内置 Noto Sans/Serif SC 为 SIL OFL 1.1 许可，可自由使用与再分发。

---

## 许可证

代码 MIT；字体 SIL OFL 1.1。
