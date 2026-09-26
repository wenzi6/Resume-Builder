# Resume Studio 交付文档（HANDOFF）

> **用途**：把项目完整交接给下一位 Agent。
> **生成时间**：2026-09-27　|　**HEAD**：`4842990`　|　分支 `master` → `origin/main`
> **配套**：`README.md`（产品说明书）｜`docs/SPEC.md`（完整规格）｜`docs/research/`（早期调研）
> **阅读顺序**：§1 摘要 → §3 代码地图 → §4 当前状态与坑 → §8 建议下一步

---

## 1. 三十秒摘要

**项目**：`resume-builder`（Resume Studio）—— 本地单用户简历工作台。

- **启动**：`PYTHONPATH=. python app.py` → http://localhost:5000（Windows 已验证，仅绑 127.0.0.1）
- **技术栈**：Python + Flask + 原生 ES Modules 前端（**无构建步骤**）+ SQLite + Chromium（PDF 渲染）+ PyMuPDF（PDF 补丁）
- **当前状态**：**完整产品水准**。pytest **306 passed / 1 skipped**；前端 13 文件语法检查通过；视觉基线齐备
- **GitHub**：https://github.com/wenzi6/Resume-Builder（HTTPS + Git Credential Manager，push 不弹窗）

**核心能力**：PDF 对照导入（原格式保留）+ **原格式实时预览**、6 套模板、AI 五项能力（用户自带 Key）、对话改简历、多配置管理、数据安全三件套、运行日志、一键清空。

---

## 2. 用户与沟通方式（重要）

- **非技术终使用者**，Windows，反馈方式 = **截图 + 一句话**（截图放 `E:\谷歌下载\`）
- 语言：中文
- 在意优先级：**排版完美 > 导入准确 > AI 能力 > 数据安全**
- **典型处理范式**（本 sessions 验证有效）：
  1. 看截图定位 → 写 `output/_diag.py` 直接调 service 复现（**别急着开浏览器**）
  2. 修 → 加回归测试 → 跑全量 → 提交推送
  3. **重启服务**（改 Python 必须；纯静态文件也要提醒用户 Ctrl+F5）
  4. 交付时附：改了什么 / 为什么 / 验证结果 / **用户需要做什么**

> ⚠️ 用户的截图常常是**修复部署前的旧渲染**。排查「看不到效果」类反馈时，先用当前代码跑一遍确认，再让用户刷新。

---

## 3. 代码地图

```
app.py                          入口 → resume_builder.main()
resume_builder/
  __init__.py                   应用工厂：日志初始化 / 蓝图 / 备份线程 / 全局 errorhandler
  config.py                     DATA_DIR / FONTS_DIR / DB_PATH / PORT / ALLOWED_ORIGINS
  schema.py                     ★文档 schema、DEFAULT_DESIGN、normalize_document、
                                 _normalize_content（★skills/free/simple 合并逻辑）、
                                 _clean_section_design（★区块级 design 白名单）
  registry.py                    ★内置区块定义（字段/类型/标签）——加字段改这里
  logging_setup.py               轮转日志 data/logs/resume-studio.log（5MB×3）
  api/                           蓝图：documents / render / export / imports / fonts /
                                 llm / analyze / backups / logs / legacy / templates
  services/
    documents.py                 文档 CRUD、版本历史、原始 PDF 生命周期、clear_all_documents
    pdf_import.py                ★PDF 解析：分桶 / _parse_work / _parse_projects /
                                 _parse_educations / _split_achievements / detect_section_titles
    pdf_patch.py                 ★★原格式补丁（**最复杂、bug 最集中**，800+ 行）
    source_pdf.py                原格式页面渲染（按内容哈希缓存 PNG）
    llm.py                       AI 能力 + chat_stream / chat_stream_rich（思考流）
    analyze.py                   本地 JD 匹配（不调 AI）
    bundle.py                    备份 / 全量导出导入
  engine/
    pdf.py                       Chromium 渲染 + 常驻 worker 池
    sections.py                  ★区块渲染（render_array / render_free / RENDERERS）
    base_css.py                  ★模板基础 CSS（.rfree / .ritem-ach / 列表标记 / 成果分组）
    tokens.py                    字体（FONT_FILES 只允许 glyf TTF）
static/
  editor.html                    单页外壳（所有弹窗）
  editor.css
  js/app.js                      boot / store 事件 / 原格式实时预览 / 视图切换
  js/store.js                    ★全局状态 + 防抖（touch→300ms 预览 / 800ms 保存）
  js/components/                 form / sidebar / designPanel / aiPanel / preview /
                                 pagination / jsonEditor / toast
  js/errorReporter.js            前端错误 → 服务端日志
tests/                           306 用例 + baselines/ 视觉基线
output/                          临时产物（gitignored）
```

---

## 4. 当前状态

### 4.1 近轮次已完成

| 功能 | 要点 |
|---|---|
| PDF 导入公司/职位精确拆分 | 「加粗行=公司+日期 / 非加粗短行=职位」；`detect_section_titles` 采用 PDF 原区块名 |
| 教育背景保留「主修课程：」标签 | 备注行不剥标签；字段改名「备注 / 主修课程」 |
| 区块改名 / 隐藏标题 / 隐藏区块 | 同步进原格式预览与导出（`_section_changes`） |
| 删除条目 / 删整个区块 | diff 按**内容**（LCS），不按索引 |
| 孤立圆点残留 | 文字圆点 + **矢量圆点**（`get_drawings` + `_bullet_art_rects`）双路清除 |
| 工作成果模块 | 导入自动拆分职责/成果；小标题复用 `ritem-sub`（**与职位同款、随模板变化**）+ 可自定义 + 带冒号 |
| 技能区自由大框 | 星级/pill 全去掉；一个多行输入 + `.rfree` 文本块 |
| 列表标记自定义 | dot/dash/arrow/none/custom，全局 + 区块级 |
| AI 对话改简历 | 字段清单防瞎编 / 差异卡片 / 逐条+全部应用 / 改完定位高亮 / Ctrl+Z |
| 新增内容在原格式可见 | 有空间插入；放不下画绿色虚线标注框（`unplaced`） |
| 运行日志 | 后端异常堆栈 + 前端 JS 错误 + API 5xx；「查看日志」对话框 |
| 一键清空 | 简历列表（先自动备份）+ 备份列表 |
| 多配置管理 | AI 配置多套命名、自动保存、切换/新建/删除 |

### 4.2 ⚠️ 待办 / 风险点（**必读**）

1. **`pdf_patch.diff_content` 的「移动」识别漏过三次分支**（列表删除、列表新增、**标量删除/替换**）。每次漏都导致原格式预览大片内容消失（技能整段没了就是这么来的）。
   → **改这个函数时，四个分支都必须有 `_moved` / `_relocated` 判断**：标量删除、标量替换、列表增、列表删。
2. **`_append_new_line` 只处理「行内有垂直空间」**；放不下时靠前端标注框。用户反馈「加了内容原格式看不到」时，先看工具条是「已同步 N 处」还是「N 处新内容放不进原版式（已在页面绿框标注）」。
3. **旧文档的 sections 是快照**，新字段靠 `normalize_document` 在**保存时**刷新。用户不保存就不刷新——引导点「↻ 重新解析」或重新导入。
4. **视觉基线**：改 `engine/base_css.py` 或任何模板 CSS 后必须 `REGEN_BASELINES=1 ... test_visual_regression.py` 重建。
5. **`data/imports/` 曾被测试误删**（见 commit `e0a2aef` 的修复：测试漏 patch `store.DATA_DIR`）。现有空表安全阀 + 回归用例。**跑任何涉及 `create_app()` 的测试前，确认夹具 patch 了该服务模块级的 `DATA_DIR`**。
6. **Git 推送偶发 TLS 错误**：重试即可，本地 commit 不丢。

---

## 5. 环境坑（都踩过，勿重复）

| # | 坑 | 规避 |
|---|---|---|
| 1 | `ctx_execute` 沙箱走 **PowerShell**，heredoc 不可用 | 含中文的临时脚本一律用 **write 工具**写文件，再用 bash 跑 |
| 2 | bash heredoc 会把 `\n` 转成真换行 | 写含 `\n` 的代码用**编辑工具**，别用 heredoc |
| 3 | Python 脚本批量 `str.replace` **静默失败**（断言在但写盘前抛异常 / 匹配不到） | 替换后**必须 grep 验证**；已因此漏过 3 次 |
| 4 | 用「找下一个 function」删函数，若目标是文件里最后一个会把其后所有 `export` 删掉（form.js 事故） | 删函数后 `grep -c "^export"` 核对数量 |
| 5 | `dataset.xxxYyy` → 属性是 `data-xxx-yyy`，`querySelectorAll("[data-xxxYyy]")` 永不匹配 | 用连字符形式 |
| 6 | Windows 中文路径 PyMuPDF C 层不接受 | 诊断脚本先把 PDF 复制到 temp 用 ASCII 名 |
| 7 | **Flask 无热重载** | 改 Python 后必须重启服务再测 UI |
| 8 | 测试会写真实 DB（UI 验收脚本） | 跑完清理（`output/_cleanup.py` 模式），别把测试文档留给用户 |
| 9 | Playwright 点击被弹窗遮挡 | 操作前 `document.getElementById('aiOverlay').hidden = true` |
| 10 | 同一秒内 `backup_db(force=True)` 文件名相同互相覆盖 | 测试造多份备份要手动写不同名文件 |

---

## 6. 数据与文件位置

| 路径 | 内容 | gitignored |
|---|---|---|
| `data/resumes.db` | 全部文档 + 版本历史 | ✅ |
| `data/backups/` | SQLite 备份（保留 10 份） | ✅ |
| `data/imports/` | 对照导入的原始 PDF + 渲染缓存 PNG | ✅ |
| `data/logs/resume-studio.log` | 运行日志 | ✅ |
| `data/llm_configs.json` / `llm_configs.json` | AI 配置（含 Key） | ✅ |
| `fonts/` | 内置 Noto Sans/Serif SC（OFL） | 部分（只提交 ttf） |
| `output/` | 临时产物 | ✅ |

> ⚠️ `data/resumes.db` 有**用户真实简历**。任何批量删除前先备份。

---

## 7. 提交与部署流程

```bash
# 1. 验证
PYTHONPATH=. python -m pytest tests/ -q
node scripts/check_js.mjs

# 2. 提交（中文信息，写清根因）
git add -A
git -c user.name="Resume Studio" -c user.email="dev@resume-studio.local" commit -F msg.txt
git push origin master:main

# 3. 重启（改 Python 必须）
for pid in $(netstat -ano | grep ":5000" | grep LISTENING | awk '{print $5}' | sort -u); do taskkill //F //PID $pid; done
PYTHONPATH=. nohup python app.py > output/server.log 2>&1 &
```

---

## 8. 建议的下一步（按优先级）

1. **原格式预览的自动化视觉验收**：现在只能靠截图人眼判断，容易漏（技能消失那次就是先看文本行没看渲染图才发现）。建议对 `patch_pdf` 输出做「渲染 → 与原文 diff 像素/文本」的断言。
2. **拆分 `pdf_patch.py`**：diff / 定位 / 插入 / 样式四职责混在 800+ 行里。建议拆 `diff.py` + `locate.py` + `insert.py`，并给 `diff_content` 补**属性测试**（fuzz：随机增删改移 → 期望变更集）。
3. **AI「指哪改哪」快捷入口**：表单字段旁的 ✨ 目前只做自动润色；加一个「让 AI 按我的要求改这个字段」直接带路径，省得 AI 猜路径。
4. **多页 PDF 的分页保持**：内容变长导致跨页时，原格式补丁可能挤压后续页。
5. **用户自有字体在原格式插入时不可用**（只有内置 Noto）；要么转换嵌入，要么在 UI 明示。

---

## 9. 用户历史 bug 模式（供预判）

| 类别 | 典型反馈 | 高发位置 |
|---|---|---|
| 导入解析 | 「XX 没匹配上」「匹配到公司了」 | `pdf_import.py` 分桶 / 拆分 |
| 原格式不同步 | 「删了还在」「加了不显示」「字体对不上」 | `pdf_patch.py` |
| 视觉一致性 | 「小框太固定」「标题样式不一样」「黑点去不掉」 | `sections.py` / `base_css.py` / 模板 CSS 覆盖 |
| AI | 「填了说没填」「保存不了」「还是分析上一个简历」 | `aiPanel.js` 模块级状态未随 `doc-swapped` 重置 |

---

## 10. 关键约定（改代码前必读）

- **表单路径**：`content.<section>.<idx>.<field>`，写入 `store.doc` 后 `store.touch()`
- **`store.doc` 保存后不整体替换**（闭包引用问题，历史坑 #2）
- **预览 iframe 同源**，可直接访问 `contentDocument`
- **区块类型**：`object` / `array` / `free`（原 skills+simple 已统一）/ `simple`
- **要做「和某元素完全同款」的样式，复用同一个 class**，不要复制 CSS 值——模板级覆盖只作用于原 class（成果小标题就是这么修的）
- **原格式导出的 diff 以「内容在哪」为准，不以「在哪个字段」为准**（移动不算改动）
