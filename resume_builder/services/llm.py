"""LLM 能力：OpenAI 兼容协议的简历 AI（润色 / 生成 / 建议 / JD 定制）。

设计原则：
- **不引入第三方依赖**：用标准库 urllib 直连 /chat/completions
- **Key 不出本机**：配置存 data/llm_config.json（gitignored），GET 永不返回 key
- **可测试**：HTTP 传输层 _http_post 可被 monkeypatch，测试不发真实请求
- **容错解析**：模型输出剥掉 markdown 围栏、截取首个 JSON 对象，失败有明确错误
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import config
from ..schema import normalize_document

CONFIG_PATH = config.DATA_DIR / "llm_config.json"

# 服务商预设（format = API 协议格式，见下方格式适配器）
#   openai    —— OpenAI 兼容 /chat/completions（绝大多数服务商）
#   azure     —— Azure OpenAI（URL 带 deployment + api-version，api-key 头）
#   anthropic —— Anthropic Claude 原生 /v1/messages（x-api-key 头，system 顶层参数）
#   gemini    —— Google Gemini 原生 generateContent（key 走 URL 参数，contents/parts）
PROVIDER_PRESETS = [
    # ---- 国内 ----
    {"id": "deepseek", "name": "DeepSeek", "group": "国内", "base_url": "https://api.deepseek.com", "model": "deepseek-chat", "format": "openai"},
    {"id": "zhipu", "name": "智谱 AI (GLM)", "group": "国内", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-plus", "format": "openai"},
    {"id": "qwen", "name": "通义千问 (DashScope)", "group": "国内", "base_url": "https://dashscope.aliyuncs.com/compatible-mode", "model": "qwen-plus", "format": "openai"},
    {"id": "kimi", "name": "Kimi (Moonshot)", "group": "国内", "base_url": "https://api.moonshot.cn", "model": "moonshot-v1-8k", "format": "openai"},
    {"id": "doubao", "name": "火山方舟 (豆包)", "group": "国内", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-pro-32k", "format": "openai"},
    {"id": "minimax", "name": "MiniMax", "group": "国内", "base_url": "https://api.minimax.chat/v1", "model": "MiniMax-Text-01", "format": "openai"},
    {"id": "hunyuan", "name": "腾讯混元", "group": "国内", "base_url": "https://api.hunyuan.cloud.tencent.com/v1", "model": "hunyuan-turbo", "format": "openai"},
    {"id": "qianfan", "name": "百度千帆", "group": "国内", "base_url": "https://qianfan.baidubce.com/v2", "model": "ernie-4.5-8k", "format": "openai"},
    {"id": "yi", "name": "零一万物", "group": "国内", "base_url": "https://api.lingyiwanwu.com/v1", "model": "yi-lightning", "format": "openai"},
    {"id": "stepfun", "name": "阶跃星辰", "group": "国内", "base_url": "https://api.stepfun.com/v1", "model": "step-2-16k", "format": "openai"},
    {"id": "siliconflow", "name": "硅基流动 SiliconFlow", "group": "国内", "base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-7B-Instruct", "format": "openai"},
    # ---- 海外 ----
    {"id": "openai", "name": "OpenAI", "group": "海外", "base_url": "https://api.openai.com", "model": "gpt-4o-mini", "format": "openai"},
    {"id": "anthropic", "name": "Anthropic Claude", "group": "海外", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-4-5", "format": "anthropic"},
    {"id": "gemini", "name": "Google Gemini", "group": "海外", "base_url": "https://generativelanguage.googleapis.com", "model": "gemini-2.0-flash", "format": "gemini"},
    {"id": "azure", "name": "Azure OpenAI", "group": "海外", "base_url": "https://YOUR-RESOURCE.openai.azure.com", "model": "gpt-4o-mini", "format": "azure"},
    {"id": "xai", "name": "xAI (Grok)", "group": "海外", "base_url": "https://api.x.ai", "model": "grok-3-mini", "format": "openai"},
    {"id": "openrouter", "name": "OpenRouter (模型聚合)", "group": "海外", "base_url": "https://openrouter.ai/api", "model": "openai/gpt-4o-mini", "format": "openai"},
    {"id": "groq", "name": "Groq", "group": "海外", "base_url": "https://api.groq.com/openai", "model": "llama-3.3-70b-versatile", "format": "openai"},
    {"id": "together", "name": "Together AI", "group": "海外", "base_url": "https://api.together.xyz", "model": "Qwen/Qwen2.5-7B-Instruct", "format": "openai"},
    {"id": "mistral", "name": "Mistral", "group": "海外", "base_url": "https://api.mistral.ai", "model": "mistral-small-latest", "format": "openai"},
    # ---- 本地 / 自建 ----
    {"id": "ollama", "name": "Ollama (本地)", "group": "本地", "base_url": "http://localhost:11434", "model": "qwen2.5:7b", "format": "openai"},
    {"id": "lmstudio", "name": "LM Studio (本地)", "group": "本地", "base_url": "http://localhost:1234", "model": "qwen2.5-7b-instruct", "format": "openai"},
    {"id": "vllm", "name": "vLLM (自建)", "group": "本地", "base_url": "http://localhost:8000", "model": "Qwen/Qwen2.5-7B-Instruct", "format": "openai"},
    {"id": "oneapi", "name": "One API / New API (中转)", "group": "本地", "base_url": "http://localhost:3000", "model": "deepseek-chat", "format": "openai"},
]

# 可手动选择的 API 格式（自定义服务商时用）
API_FORMATS = [
    {"id": "openai", "name": "OpenAI 兼容（/chat/completions）"},
    {"id": "anthropic", "name": "Anthropic 原生（/v1/messages）"},
    {"id": "gemini", "name": "Google Gemini 原生（generateContent）"},
    {"id": "azure", "name": "Azure OpenAI"},
]

DEFAULT_CONFIG: dict[str, Any] = {
    "base_url": "",
    "api_key": "",
    "model": "",
    "format": "openai",
    "timeout": 90,
}

MAX_TIMEOUT = 300

# Anthropic 协议版本头
ANTHROPIC_VERSION = "2023-06-01"
# Azure OpenAI api-version
AZURE_API_VERSION = "2024-06-01"


# ---------------------------------------------------------------- 配置


def _config_path() -> Path:
    return config.DATA_DIR / "llm_config.json"


def load_config() -> dict[str, Any]:
    """读取配置（含 key，仅服务端使用）。"""
    cfg = dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(_config_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update({k: raw[k] for k in DEFAULT_CONFIG if k in raw})
    except (OSError, json.JSONDecodeError):
        pass
    cfg["timeout"] = max(10, min(int(cfg.get("timeout") or 90), MAX_TIMEOUT))
    return cfg


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """保存配置（只认白名单字段；key 允许为空表示保留不动由调用方处理）。"""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_config()
    fmt = str(cfg.get("format") or "openai")
    if fmt not in {f["id"] for f in API_FORMATS}:
        fmt = "openai"
    out = {
        "base_url": str(cfg.get("base_url") or "").strip().rstrip("/"),
        "model": str(cfg.get("model") or "").strip()[:80],
        "format": fmt,
        "timeout": max(10, min(int(cfg.get("timeout") or 90), MAX_TIMEOUT)),
    }
    # api_key：传入空串表示保留原值（前端「不修改 key」的语义）
    key = str(cfg.get("api_key") or "").strip()
    out["api_key"] = key if key else current.get("api_key", "")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def public_config() -> dict[str, Any]:
    """给前端的配置视图：绝不返回 key 本身。"""
    cfg = load_config()
    return {
        "configured": bool(cfg["base_url"] and cfg["api_key"] and cfg["model"]),
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "format": cfg["format"],
        "has_key": bool(cfg["api_key"]),
        "timeout": cfg["timeout"],
        "presets": PROVIDER_PRESETS,
        "formats": API_FORMATS,
    }


# ---------------------------------------------------------------- HTTP 传输


def _http_post(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    """OpenAI 兼容 POST（测试可 monkeypatch 此函数）。"""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _friendly_error(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        if e.code in (401, 403):
            return f"API Key 无效或无权限（HTTP {e.code}）。请检查设置中的 Key。{body}"
        if e.code == 404:
            return f"接口不存在（HTTP 404）：请确认 Base URL 填写正确（应到域名/IP 为止，不带 /chat/completions）。{body}"
        if e.code == 429:
            return f"请求被限流或额度不足（HTTP 429）。{body}"
        return f"服务端错误 HTTP {e.code}：{body}"
    if isinstance(e, urllib.error.URLError):
        reason = getattr(e, "reason", e)
        if "timed out" in str(reason).lower():
            return "连接超时：请检查网络 / Base URL，或在设置中加大超时时间。"
        return f"网络错误：{reason}。本地服务（如 Ollama）请确认已启动。"
    if isinstance(e, TimeoutError):
        return "连接超时：请检查网络或在设置中加大超时时间。"
    return str(e)


# ---------------------------------------------------------------- 协议格式适配器
#
# 每种 format 负责三件事：
#   build_request(cfg, messages, temperature, max_tokens) -> (url, headers, payload)
#   parse_response(data) -> str
# 新增一种第三方协议 = 加两个函数 + 注册进 _FORMATS。


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """把 system 消息拆出来（Anthropic/Gemini 的 system 是顶层参数）。"""
    system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    return "\n\n".join(p for p in system_parts if p), rest


def _merge_consecutive(messages: list[dict]) -> list[dict]:
    """合并连续同角色消息（Anthropic 要求 user/assistant 交替）。"""
    out: list[dict] = []
    for m in messages:
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n\n" + m["content"]
        else:
            out.append(dict(m))
    return out


def _build_openai(cfg, messages, temperature, max_tokens):
    return (
        f"{cfg['base_url']}/chat/completions",
        {"Authorization": f"Bearer {cfg['api_key']}"},
        {"model": cfg["model"], "messages": messages,
         "temperature": temperature, "max_tokens": max_tokens, "stream": False},
    )


def _parse_openai(data):
    return data["choices"][0]["message"]["content"]


def _build_azure(cfg, messages, temperature, max_tokens):
    # URL: {base}/openai/deployments/{model}/chat/completions?api-version=...
    return (
        f"{cfg['base_url']}/openai/deployments/{cfg['model']}/chat/completions"
        f"?api-version={AZURE_API_VERSION}",
        {"api-key": cfg["api_key"]},
        {"messages": messages, "temperature": temperature,
         "max_tokens": max_tokens, "stream": False},
    )


def _parse_azure(data):
    return data["choices"][0]["message"]["content"]


def _build_anthropic(cfg, messages, temperature, max_tokens):
    system, rest = _split_system(messages)
    rest = _merge_consecutive(rest)
    # Anthropic 的 role 只有 user/assistant
    conv = [{"role": ("assistant" if m["role"] == "assistant" else "user"),
             "content": m.get("content", "")} for m in rest]
    payload: dict[str, Any] = {
        "model": cfg["model"],
        "messages": conv,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
        payload["system"] = system
    return (
        f"{cfg['base_url']}/v1/messages",
        {"x-api-key": cfg["api_key"], "anthropic-version": ANTHROPIC_VERSION},
        payload,
    )


def _parse_anthropic(data):
    # content 是 block 数组，取所有 text block 拼接
    blocks = data.get("content") or []
    texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    return "".join(texts)


def _build_gemini(cfg, messages, temperature, max_tokens):
    system, rest = _split_system(messages)
    contents = []
    for m in _merge_consecutive(rest):
        contents.append({
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m.get("content", "")}],
        })
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    # Gemini 的 key 走 URL 查询参数
    sep = "&" if "?" in cfg["base_url"] else "?"
    return (
        f"{cfg['base_url']}/v1beta/models/{cfg['model']}:generateContent{sep}key={cfg['api_key']}",
        {},
        payload,
    )


def _parse_gemini(data):
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


_FORMATS = {
    "openai": (_build_openai, _parse_openai),
    "azure": (_build_azure, _parse_azure),
    "anthropic": (_build_anthropic, _parse_anthropic),
    "gemini": (_build_gemini, _parse_gemini),
}


def chat(messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000) -> str:
    """调用对话模型，返回文本内容（按配置的 format 走对应协议）。"""
    cfg = load_config()
    if not (cfg["base_url"] and cfg["api_key"] and cfg["model"]):
        raise ValueError("AI 尚未配置：请先在「AI 设置」中填写 Base URL / API Key / 模型")
    fmt = cfg.get("format") or "openai"
    build, parse = _FORMATS.get(fmt, _FORMATS["openai"])
    url, headers, payload = build(cfg, messages, temperature, max_tokens)
    try:
        data = _http_post(url, headers, payload, cfg["timeout"])
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(_friendly_error(e)) from e
    try:
        text = parse(data).strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"AI 返回格式异常（{fmt}）：{str(data)[:200]}") from e
    if not text:
        raise RuntimeError(f"AI 返回了空内容（{fmt}）")
    return text


def test_connection() -> dict:
    """用最小请求验证配置可用性。"""
    try:
        text = chat(
            [{"role": "user", "content": "回复「连接成功」四个字"}],
            temperature=0,
            max_tokens=20,
        )
        return {"ok": True, "message": f"连接成功，模型回复：{text[:40]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)}


# ---------------------------------------------------------------- 输出解析


def _extract_json(text: str) -> Any:
    """从模型输出提取 JSON（剥围栏 / 截取首个花括号段）。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError("AI 未返回有效的 JSON，请重试或换个模型")


# ---------------------------------------------------------------- 能力 1：润色


def polish_text(text: str, context: str = "") -> dict:
    """按 Google XYZ 公式润色单条内容。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("请输入要润色的内容")
    if len(text) > 800:
        raise ValueError("单条内容过长（上限 800 字），请分段润色")
    ctx = f"\n所在上下文：{context}" if context else ""
    messages = [
        {
            "role": "system",
            "content": (
                "你是资深简历顾问。按 Google XYZ 公式改写用户给的简历条目："
                "「 Accomplished X as measured by Y by doing Z 」——即「做了什么 + 可量化结果 + 怎么做」。"
                "铁律：不得编造用户没提供的数据；原文没有数值时用「显著提升」「有效降低」等表述，"
                "或提示用户补充数值。每条以强动词开头，不超过 60 字，中文输出（英文原文则英文输出）。"
                "只输出改写后的 1-3 条，每行一条，不要编号、不要解释。"
            ),
        },
        {"role": "user", "content": f"请润色以下简历内容{ctx}：\n{text}"},
    ]
    result = chat(messages, temperature=0.6, max_tokens=600)
    return {"original": text, "result": result}


# ---------------------------------------------------------------- 能力 2：生成简历


_GEN_SCHEMA_HINT = """{
  "profile": {"name": "", "title": "", "email": "", "phone": "", "location": "", "summary": ""},
  "workExperiences": [{"company": "", "jobTitle": "", "date": "YYYY-MM – 至今", "descriptions": ["…"]}],
  "projects": [{"project": "", "jobTitle": "", "date": "YYYY-MM – YYYY-MM", "descriptions": ["…"]}],
  "educations": [{"school": "", "degree": "本科 · 专业", "date": "YYYY-MM – YYYY-MM", "descriptions": ["…"]}],
  "skills": {"featuredSkills": [{"skill": "", "rating": 4}], "descriptions": ["…"]},
  "selfEvaluation": {"descriptions": ["…"]}
}"""


def generate_resume(brief: dict) -> dict:
    """根据简要信息生成结构化简历内容。"""
    if not isinstance(brief, dict):
        raise ValueError("参数错误")
    name = str(brief.get("name") or "").strip()
    title = str(brief.get("title") or "").strip()
    if not title:
        raise ValueError("请至少填写「目标岗位」")
    parts = [f"目标岗位：{title}"]
    if name:
        parts.append(f"姓名：{name}")
    for key, label in (("years", "工作年限"), ("skills", "技能栈"), ("highlights", "经历要点"),
                       ("education", "教育背景"), ("location", "所在城市")):
        v = str(brief.get(key) or "").strip()
        if v:
            parts.append(f"{label}：{v}")
    messages = [
        {
            "role": "system",
            "content": (
                "你是资深简历顾问。根据用户提供的基本信息，生成一份专业、真实、可量化的中文简历内容。"
                "铁律：用户没提供的信息（公司名、项目名、具体数值）用占位符如「某科技公司」「XX 项目」并保持合理，"
                "不要虚构具体公司名；描述遵循 Google XYZ 公式，动词开头、结果导向；数量 2-4 个区块、每区块 1-3 条。"
                "严格只输出 JSON（不要 markdown 围栏），结构如下：\n" + _GEN_SCHEMA_HINT
            ),
        },
        {"role": "user", "content": "\n".join(parts)},
    ]
    data = _extract_json(chat(messages, temperature=0.7, max_tokens=2500))
    if not isinstance(data, dict):
        raise ValueError("AI 返回结构异常")
    # 包成文档走归一化，保证形状合法
    doc = normalize_document({"version": 2, "content": data})
    return {"content": doc["content"], "brief": brief}


# ---------------------------------------------------------------- 能力 3：修改建议


def suggest_improvements(document: dict) -> dict:
    """通读简历给出修改建议。"""
    doc = normalize_document(document)
    # 只发给 AI 必要的文本，减少 token 与隐私暴露
    slim = {
        "title": doc.get("title", ""),
        "templateId": doc.get("templateId", ""),
        "content": doc.get("content", {}),
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是资深简历顾问与 ATS 专家。审查用户的简历 JSON，给出具体、可执行的修改建议。"
                "维度：① 量化成果（无数值的 bullet）② 动词强度 ③ 关键词与岗位匹配度 ④ 冗长/重复 "
                "⑤ 时间线与完整性 ⑥ ATS 友好度。每条建议指出 section（区块 key）、优先级（high/medium/low）、"
                "问题、改法、以及一条示例文案。严格只输出 JSON："
                "{\"suggestions\": [{\"section\": \"workExperiences\", \"priority\": \"high\", "
                "\"issue\": \"…\", \"suggestion\": \"…\", \"example\": \"…\"}], \"summary\": \"总体评价\"}"
            ),
        },
        {"role": "user", "content": json.dumps(slim, ensure_ascii=False)},
    ]
    data = _extract_json(chat(messages, temperature=0.5, max_tokens=2500))
    suggestions = data.get("suggestions") if isinstance(data, dict) else None
    if not isinstance(suggestions, list):
        raise ValueError("AI 未返回建议列表，请重试")
    clean = []
    for s in suggestions[:20]:
        if isinstance(s, dict) and s.get("suggestion"):
            clean.append({
                "section": str(s.get("section") or "")[:40],
                "priority": s.get("priority") if s.get("priority") in ("high", "medium", "low") else "medium",
                "issue": str(s.get("issue") or "")[:200],
                "suggestion": str(s.get("suggestion") or "")[:400],
                "example": str(s.get("example") or "")[:300],
            })
    return {"suggestions": clean, "summary": str(data.get("summary") or "")[:300]}


# ---------------------------------------------------------------- 能力 4：JD 定制改写


def tailor_to_jd(document: dict, jd: str) -> dict:
    """按 JD 关键词改写简历条目（不编造经历）。"""
    jd = (jd or "").strip()
    if not jd:
        raise ValueError("请粘贴 JD（职位描述）文本")
    if len(jd) > 6000:
        raise ValueError("JD 过长（上限 6000 字）")
    doc = normalize_document(document)
    slim = {"content": doc.get("content", {})}
    messages = [
        {
            "role": "system",
            "content": (
                "你是资深简历顾问。根据 JD 关键词，改写用户的简历条目，使其更贴合目标岗位。"
                "铁律：只能重新组织与强化用户已有的真实经历与技能，不得编造新经历、新公司、新数据；"
                "优先自然融入 JD 中的硬技能关键词。"
                "严格只输出 JSON："
                "{\"rewrites\": [{\"section\": \"workExperiences\", \"index\": 0, \"field\": \"descriptions\", "
                "\"item\": 1, \"original\": \"原文\", \"rewritten\": \"改写后\"}], "
                "\"missing\": [\"JD 要求但简历未体现的关键词\"], \"summary\": \"总体匹配度简评\"}"
                " rewrites 不超过 8 条，只挑最值得改的。"
            ),
        },
        {"role": "user", "content": f"JD：\n{jd}\n\n简历：\n{json.dumps(slim, ensure_ascii=False)}"},
    ]
    data = _extract_json(chat(messages, temperature=0.6, max_tokens=3000))
    rewrites = data.get("rewrites") if isinstance(data, dict) else None
    if not isinstance(rewrites, list):
        raise ValueError("AI 未返回改写列表，请重试")
    clean = []
    for r in rewrites[:8]:
        if isinstance(r, dict) and r.get("rewritten"):
            clean.append({
                "section": str(r.get("section") or "")[:40],
                "index": int(r["index"]) if str(r.get("index", "")).isdigit() else 0,
                "field": str(r.get("field") or "descriptions")[:40],
                "item": int(r["item"]) if str(r.get("item", "")).isdigit() else 0,
                "original": str(r.get("original") or "")[:400],
                "rewritten": str(r.get("rewritten") or "")[:600],
            })
    missing = [str(m)[:40] for m in (data.get("missing") or []) if isinstance(m, (str, int))][:15]
    return {"rewrites": clean, "missing": missing, "summary": str(data.get("summary") or "")[:300]}
