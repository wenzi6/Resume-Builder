"""LLM 功能回归：配置安全 / 四项能力 / 错误路径（全部 mock 传输层）。"""
from __future__ import annotations

import json

import pytest

from resume_builder.sample import sample_general
from resume_builder.services import llm


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """隔离配置目录，测试不碰真实 data/llm_config.json。"""
    monkeypatch.setattr(llm.config, "DATA_DIR", tmp_path)
    yield tmp_path


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    """隔离配置目录并预置一套初始配置，返回目录 Path（多配置测试用）。"""
    monkeypatch.setattr(llm.config, "DATA_DIR", tmp_path)
    (tmp_path / "llm_config.json").unlink(missing_ok=True)
    (tmp_path / "llm_configs.json").write_text(json.dumps({
        "active": "init",
        "configs": [{"id": "init", "name": "初始", "base_url": "", "api_key": "",
                     "model": "", "format": "openai", "timeout": 90}],
    }), encoding="utf-8")
    return tmp_path


def _mock_chat(monkeypatch, reply: str):
    """mock _http_post，返回指定的 assistant 内容；记录调用参数。"""
    calls = []

    def fake_post(url, headers, payload, timeout):
        calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return {"choices": [{"message": {"content": reply}}]}

    monkeypatch.setattr(llm, "_http_post", fake_post)
    return calls


def _mock_raw(monkeypatch, data: dict):
    """mock _http_post 直接返回给定响应体（用于非 OpenAI 协议）。"""
    calls = []

    def fake_post(url, headers, payload, timeout):
        calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return data

    monkeypatch.setattr(llm, "_http_post", fake_post)
    return calls


def _configured(**overrides):
    cfg = {"base_url": "https://api.example.com", "api_key": "sk-test", "model": "test-model", "timeout": 30}
    cfg.update(overrides)
    return llm.save_config(cfg)


# ---------------- 配置安全 ----------------

def test_config_roundtrip_and_key_hidden():
    _configured()
    public = llm.public_config()
    assert public["configured"] is True
    assert public["base_url"] == "https://api.example.com"
    assert public["model"] == "test-model"
    assert public["has_key"] is True
    # 关键：公网视图绝不泄露 key
    assert "api_key" not in public
    assert "sk-test" not in json.dumps(public)


def test_config_unconfigured_by_default():
    public = llm.public_config()
    assert public["configured"] is False
    assert public["has_key"] is False


def test_save_config_empty_key_keeps_existing():
    _configured()
    llm.save_config({"base_url": "https://api.example.com", "model": "m2", "api_key": ""})
    assert llm.load_config()["api_key"] == "sk-test"  # 保留原值


def test_config_stored_on_disk_only():
    _configured()
    path = llm._configs_path()
    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    active = next(c for c in raw["configs"] if c["id"] == raw["active"])
    assert active["api_key"] == "sk-test"  # 落盘在 gitignored 的 data/ 下


def test_config_rejects_bad_input(client):
    r = client.put("/api/v1/llm/config", json={"base_url": "", "model": "m"})
    assert r.status_code == 400
    r = client.put("/api/v1/llm/config", json={"base_url": "ftp://x", "model": "m"})
    assert r.status_code == 400


# ---------------- 传输与错误 ----------------def test_chat_requires_config():
    with pytest.raises(ValueError, match="尚未配置"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_chat_posts_openai_shape(monkeypatch):
    _configured()
    calls = _mock_chat(monkeypatch, "你好")
    out = llm.chat([{"role": "user", "content": "hi"}], temperature=0.5, max_tokens=100)
    assert out == "你好"
    c = calls[0]
    assert c["url"] == "https://api.example.com/chat/completions"
    assert c["headers"]["Authorization"] == "Bearer sk-test"
    assert c["payload"]["model"] == "test-model"
    assert c["payload"]["stream"] is False
    assert c["payload"]["temperature"] == 0.5


def test_chat_http_error_friendly(monkeypatch):
    import urllib.error

    _configured()

    def boom(url, headers, payload, timeout):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(llm, "_http_post", boom)
    with pytest.raises(RuntimeError, match="API Key 无效"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_chat_timeout_friendly(monkeypatch):
    import urllib.error

    _configured()

    def boom(url, headers, payload, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(llm, "_http_post", boom)
    with pytest.raises(RuntimeError, match="超时"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_test_connection(monkeypatch):
    _configured()
    _mock_chat(monkeypatch, "连接成功")
    r = llm.test_connection()
    assert r["ok"] is True
    assert "连接成功" in r["message"]


# ---------------- 能力：润色 ----------------

def test_polish(monkeypatch):
    _configured()
    _mock_chat(monkeypatch, "重构前端架构，首屏 LCP 从 4.2s 降至 1.8s，提升用户留存 15%\n建设组件库 30+ 个，需求交付效率提升 40%")
    r = llm.polish_text("负责前端架构设计和组件库建设")
    assert "LCP" in r["result"]
    assert r["original"] == "负责前端架构设计和组件库建设"


def test_polish_empty_rejected():
    with pytest.raises(ValueError, match="请输入"):
        llm.polish_text("   ")


def test_polish_too_long_rejected():
    with pytest.raises(ValueError, match="过长"):
        llm.polish_text("字" * 801)


# ---------------- 能力：生成 ----------------

def test_generate(monkeypatch):
    _configured()
    payload = {
        "profile": {"name": "张三", "title": "前端工程师", "summary": "3 年经验"},
        "workExperiences": [{"company": "某科技公司", "jobTitle": "前端工程师",
                             "date": "2022-03 – 至今", "descriptions": ["负责核心产品前端开发"]}],
        "skills": {"featuredSkills": [{"skill": "React", "rating": 4}], "descriptions": []},
    }
    _mock_chat(monkeypatch, "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```")
    r = llm.generate_resume({"title": "前端工程师", "name": "张三", "years": "3"})
    assert r["content"]["profile"]["name"] == "张三"
    assert r["content"]["workExperiences"][0]["company"] == "某科技公司"
    assert r["content"]["skills"]["featuredSkills"][0]["skill"] == "React"


def test_generate_requires_title():
    with pytest.raises(ValueError, match="目标岗位"):
        llm.generate_resume({})


def test_generate_handles_non_json(monkeypatch):
    _configured()
    _mock_chat(monkeypatch, "抱歉，我不能生成简历。")
    with pytest.raises(ValueError, match="JSON"):
        llm.generate_resume({"title": "前端工程师"})


# ---------------- 能力：建议 ----------------

def test_suggest(monkeypatch):
    _configured()
    reply = json.dumps({
        "suggestions": [
            {"section": "workExperiences", "priority": "high", "issue": "缺少量化",
             "suggestion": "补充数值", "example": "首屏 LCP 降至 1.8s"},
            {"priority": "bogus", "suggestion": "过滤非法优先级"},  # 无 section/issue 也应保留
        ],
        "summary": "整体不错，注意量化",
    }, ensure_ascii=False)
    _mock_chat(monkeypatch, reply)
    r = llm.suggest_improvements(sample_general())
    assert len(r["suggestions"]) == 2
    assert r["suggestions"][0]["priority"] == "high"
    assert r["suggestions"][1]["priority"] == "medium"  # 非法值归一化
    assert "量化" in r["summary"]


def test_suggest_bad_shape(monkeypatch):
    _configured()
    _mock_chat(monkeypatch, '{"foo": 1}')
    with pytest.raises(ValueError, match="建议列表"):
        llm.suggest_improvements(sample_general())


# ---------------- 能力：JD 定制 ----------------

def test_tailor(monkeypatch):
    _configured()
    reply = json.dumps({
        "rewrites": [
            {"section": "workExperiences", "index": 0, "field": "descriptions", "item": 0,
             "original": "负责前端开发", "rewritten": "主导 React 前端架构，支撑日均 10 万+ 访问"},
        ],
        "missing": ["TypeScript", "性能优化"],
        "summary": "匹配度 70%",
    }, ensure_ascii=False)
    _mock_chat(monkeypatch, reply)
    r = llm.tailor_to_jd(sample_general(), "岗位要求：精通 React、TypeScript，负责性能优化")
    assert len(r["rewrites"]) == 1
    assert r["rewrites"][0]["index"] == 0
    assert "TypeScript" in r["missing"]
    assert r["rewrites"][0]["rewritten"].startswith("主导")


def test_tailor_requires_jd():
    with pytest.raises(ValueError, match="JD"):
        llm.tailor_to_jd(sample_general(), "  ")


# ---------------- 协议格式适配 ----------------

MSGS = [
    {"role": "system", "content": "你是简历顾问"},
    {"role": "user", "content": "问题一"},
    {"role": "user", "content": "问题二"},
    {"role": "assistant", "content": "回答"},
]


def test_presets_valid():
    """预设表完整且格式合法。"""
    ids = [p["id"] for p in llm.PROVIDER_PRESETS]
    assert len(ids) == len(set(ids)), "预设 id 重复"
    valid_formats = {f["id"] for f in llm.API_FORMATS}
    for p in llm.PROVIDER_PRESETS:
        assert p["format"] in valid_formats, p["id"]
        assert p["base_url"].startswith("http"), p["id"]
        assert p["model"], p["id"]
        assert p.get("group"), p["id"]
    # 四种格式都要有预设覆盖
    covered = {p["format"] for p in llm.PROVIDER_PRESETS}
    assert covered == valid_formats


def test_build_openai():
    cfg = {"base_url": "https://api.example.com", "api_key": "sk", "model": "m"}
    url, headers, payload = llm._build_openai(cfg, MSGS, 0.5, 100)
    assert url == "https://api.example.com/chat/completions"
    assert headers["Authorization"] == "Bearer sk"
    assert payload["model"] == "m" and payload["stream"] is False


def test_build_azure():
    cfg = {"base_url": "https://x.openai.azure.com", "api_key": "AK", "model": "gpt-4o-mini"}
    url, headers, payload = llm._build_azure(cfg, MSGS, 0.5, 100)
    assert "/openai/deployments/gpt-4o-mini/chat/completions" in url
    assert "api-version=" in url
    assert headers == {"api-key": "AK"}          # 不是 Bearer
    assert "model" not in payload                    # 模型在 URL 里


def test_build_anthropic():
    cfg = {"base_url": "https://api.anthropic.com", "api_key": "K", "model": "claude-x"}
    url, headers, payload = llm._build_anthropic(cfg, MSGS, 0.5, 100)
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "K"
    assert headers["anthropic-version"] == "2023-06-01"
    assert payload["system"] == "你是简历顾问"       # system 提为顶层
    assert [m["role"] for m in payload["messages"]] == ["user", "assistant"]
    assert payload["messages"][0]["content"] == "问题一\n\n问题二"  # 连续 user 合并
    assert payload["max_tokens"] == 100


def test_build_gemini():
    cfg = {"base_url": "https://generativelanguage.googleapis.com", "api_key": "GK", "model": "gemini-2.0-flash"}
    url, headers, payload = llm._build_gemini(cfg, MSGS, 0.5, 100)
    assert ":generateContent" in url and "key=GK" in url   # key 走 URL 参数
    assert headers == {}
    assert payload["systemInstruction"]["parts"][0]["text"] == "你是简历顾问"
    roles = [c["role"] for c in payload["contents"]]
    assert roles == ["user", "model"]                    # assistant → model
    assert payload["generationConfig"]["maxOutputTokens"] == 100


def test_parse_formats():
    assert llm._parse_anthropic({"content": [{"type": "text", "text": "hi"}, {"type": "text", "text": " there"}]}) == "hi there"
    assert llm._parse_gemini({"candidates": [{"content": {"parts": [{"text": "he"}, {"text": "llo"}]}}]}) == "hello"
    assert llm._parse_azure({"choices": [{"message": {"content": "ok"}}]}) == "ok"


def test_chat_dispatches_by_format(monkeypatch):
    """chat() 按配置的 format 走对应协议。"""
    cases = (
        ("anthropic", {"content": [{"type": "text", "text": "claude 回复"}]}, "claude 回复"),
        ("gemini", {"candidates": [{"content": {"parts": [{"text": "gemini 回复"}]}}]}, "gemini 回复"),
        ("azure", {"choices": [{"message": {"content": "azure 回复"}}]}, "azure 回复"),
        ("openai", {"choices": [{"message": {"content": "openai 回复"}}]}, "openai 回复"),
    )
    for fmt, reply, marker in cases:
        _configured(format=fmt)
        calls = _mock_raw(monkeypatch, reply)
        out = llm.chat([{"role": "user", "content": "hi"}])
        assert out == marker, fmt
        assert calls[0]["url"]


def test_chat_empty_content_raises(monkeypatch):
    _configured()
    _mock_raw(monkeypatch, {"choices": [{"message": {"content": ""}}]})
    with pytest.raises(RuntimeError, match="空内容"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_config_format_roundtrip():
    cfg = _configured(format="anthropic")
    assert cfg["format"] == "anthropic"
    assert llm.load_config()["format"] == "anthropic"
    assert llm.public_config()["format"] == "anthropic"
    # 非法格式回落 openai
    llm.save_config({"base_url": "https://api.example.com", "model": "m", "format": "bogus"})
    assert llm.load_config()["format"] == "openai"


def test_api_config_accepts_format(client):
    r = client.put("/api/v1/llm/config", json={
        "base_url": "https://api.anthropic.com", "model": "claude-x",
        "api_key": "k", "format": "anthropic"})
    assert r.status_code == 200
    assert r.get_json()["format"] == "anthropic"


# ---------------- 启动与清理 ----------------

def test_fresh_boot_with_empty_db(tmp_path, monkeypatch):
    """全新环境（无数据库）启动不能崩：孤立清扫曾跑在建表前。"""
    from resume_builder import config
    from resume_builder.services import documents as store
    from resume_builder import create_app

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "fresh.db")
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "fresh.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    app = create_app()
    client = app.test_client()
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/documents").status_code == 200


def test_sweep_orphans_missing_table(tmp_path, monkeypatch):
    """表不存在时清扫静默返回（不抛异常）。"""
    from resume_builder.services import documents as store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "none.db")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    (tmp_path / "imports").mkdir()
    (tmp_path / "imports" / "orphan.pdf").write_bytes(b"%PDF-1.4")
    assert store.sweep_orphan_source_pdfs(max_age_s=0) == 0  # 无表 → 不清（安全）


# ---------------- API 层 ----------------

def test_api_config_get_no_key(client):
    _configured()
    r = client.get("/api/v1/llm/config")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "sk-test" not in body
    assert r.get_json()["configured"] is True


def test_api_polish_unconfigured(client):
    r = client.post("/api/v1/llm/polish", json={"text": "x"})
    assert r.status_code == 400  # 未配置属于前置条件错误
    assert "尚未配置" in r.get_json()["error"]


def test_api_polish_ok(client, monkeypatch):
    _configured()
    _mock_chat(monkeypatch, "改写后的内容")
    r = client.post("/api/v1/llm/polish", json={"text": "原文"})
    assert r.status_code == 200
    assert r.get_json()["result"] == "改写后的内容"


def test_api_polish_empty_400(client):
    r = client.post("/api/v1/llm/polish", json={"text": ""})
    assert r.status_code == 400


def test_api_suggest_requires_document(client):
    r = client.post("/api/v1/llm/suggest", json={})
    assert r.status_code == 400


def test_api_generate_requires_brief(client):
    r = client.post("/api/v1/llm/generate", json={})
    assert r.status_code == 400


def test_api_test_connection(client, monkeypatch):
    _configured()
    _mock_chat(monkeypatch, "连接成功")
    r = client.post("/api/v1/llm/test")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


# ---------------- 流式输出 ----------------


class _FakeStreamBody:
    """模拟 SSE 响应体（逐行 yield bytes）。"""

    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        for ln in self._lines:
            yield ln.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeStreamResp:
    def __init__(self, lines):
        self._body = _FakeStreamBody(lines)

    def __enter__(self):
        return self._body

    def __exit__(self, *a):
        return False


def _mock_stream(monkeypatch, lines):
    monkeypatch.setattr(llm, "_open_stream", lambda req, timeout: _FakeStreamResp(lines))


def test_chat_stream_openai(monkeypatch):
    _configured()
    _mock_stream(monkeypatch, [
        'data: {"choices":[{"delta":{"content":"你好"}}]}',
        'data: {"choices":[{"delta":{"content":"，世界"}}]}',
        "data: [DONE]",
        "",
    ])
    out = "".join(llm.chat_stream([{"role": "user", "content": "hi"}]))
    assert out == "你好，世界"


def test_chat_stream_anthropic(monkeypatch):
    _configured(format="anthropic")
    _mock_stream(monkeypatch, [
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"text":"第一条"}}',
        'data: {"type":"content_block_delta","delta":{"text":"补充"}}',
        "data: [DONE]",
    ])
    out = "".join(llm.chat_stream([{"role": "user", "content": "hi"}]))
    assert out == "第一条补充"


def test_chat_stream_gemini(monkeypatch):
    _configured(format="gemini")
    _mock_stream(monkeypatch, [
        'data: {"candidates":[{"content":{"parts":[{"text":"Gem"}]}}]}',
        'data: {"candidates":[{"content":{"parts":[{"text":"ini"}]}}]}',
    ])
    out = "".join(llm.chat_stream([{"role": "user", "content": "hi"}]))
    assert out == "Gemini"


def test_chat_stream_empty_raises(monkeypatch):
    _configured()
    _mock_stream(monkeypatch, ["data: [DONE]"])
    with pytest.raises(RuntimeError, match="未返回任何内容"):
        list(llm.chat_stream([{"role": "user", "content": "hi"}]))


def test_chat_stream_unconfigured():
    with pytest.raises(ValueError, match="尚未配置"):
        list(llm.chat_stream([{"role": "user", "content": "hi"}]))


def test_polish_with_on_chunk(monkeypatch):
    """on_chunk 回调逐段收到增量。"""
    _configured()
    _mock_stream(monkeypatch, [
        'data: {"choices":[{"delta":{"content":"重构架构"}}]}',
        'data: {"choices":[{"delta":{"content":"，LCP 降至 1.8s"}}]}',
        "data: [DONE]",
    ])
    seen = []
    r = llm.polish_text("负责架构", on_chunk=lambda c: seen.append(c))
    assert seen == ["重构架构", "，LCP 降至 1.8s"]
    assert r["result"] == "重构架构，LCP 降至 1.8s"


def test_api_stream_polish(client, monkeypatch):
    """SSE 端点：chunk 事件 + done 结构化结果。"""
    _configured()
    _mock_stream(monkeypatch, [
        'data: {"choices":[{"delta":{"content":"改写后"}}]}',
        "data: [DONE]",
    ])
    r = client.post("/api/v1/llm/stream",
                    json={"capability": "polish", "text": "原文", "context": ""})
    assert r.status_code == 200
    assert "text/event-stream" in r.content_type
    body = r.get_data(as_text=True)
    assert '"chunk": "改写后"' in body
    assert '"done": true' in body
    assert '"result"' in body


def test_api_stream_bad_capability(client):
    r = client.post("/api/v1/llm/stream", json={"capability": "suggest"})
    assert r.status_code == 400


def test_api_stream_generate(client, monkeypatch):
    _configured()
    payload = {"profile": {"name": "流式生成", "title": "工程师", "summary": ""},
               "workExperiences": [], "projects": [], "educations": [],
               "skills": {"featuredSkills": [], "descriptions": []},
               "selfEvaluation": {"descriptions": []}}
    _mock_stream(monkeypatch, [
        'data: {"choices":[{"delta":{"content":' + json.dumps(json.dumps(payload, ensure_ascii=False)) + '}}]}',
        "data: [DONE]",
    ])
    r = client.post("/api/v1/llm/stream",
                    json={"capability": "generate", "brief": {"title": "工程师"}})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '"done": true' in body
    assert "流式生成" in body


# ---------------- 批量润色 ----------------

def test_polish_batch(monkeypatch):
    _configured()
    reply = json.dumps(["重构核心产品前端架构，首屏 LCP 降至 1.8s",
                        "建设组件库 30+ 个，需求交付效率提升 40%"], ensure_ascii=False)
    _mock_raw(monkeypatch, {"choices": [{"message": {"content": reply}}]})
    r = llm.polish_batch(["负责架构设计", "建设组件库"], context="工作经历")
    assert r["results"][0].startswith("重构")
    assert len(r["results"]) == 2


def test_polish_batch_pads_missing(monkeypatch):
    """AI 少返回时用原文补齐，数量对齐。"""
    _configured()
    _mock_raw(monkeypatch, {"choices": [{"message": {"content": '[\"只有一条\"]'}}]})
    r = llm.polish_batch(["第一条", "第二条"])
    assert r["results"] == ["只有一条", "第二条"]


def test_polish_batch_empty():
    import pytest

    with pytest.raises(ValueError, match="没有需要润色"):
        llm.polish_batch([])


def test_polish_batch_too_many():
    import pytest

    with pytest.raises(ValueError, match="最多"):
        llm.polish_batch(["x"] * 13)


def test_api_polish_batch(client, monkeypatch):
    _configured()
    reply = json.dumps(["改写一", "改写二"], ensure_ascii=False)
    _mock_raw(monkeypatch, {"choices": [{"message": {"content": reply}}]})
    r = client.post("/api/v1/llm/polish-batch", json={"items": ["原文一", "原文二"], "context": "项目"})
    assert r.status_code == 200
    assert r.get_json()["results"] == ["改写一", "改写二"]


def test_api_polish_batch_requires_items(client):
    r = client.post("/api/v1/llm/polish-batch", json={})
    assert r.status_code == 400


# ---------------- 对话 ----------------

def test_api_chat_stream(client, monkeypatch):
    _configured()
    _mock_stream(monkeypatch, [
        'data: {"choices":[{"delta":{"content":"可以"}}]}',
        'data: {"choices":[{"delta":{"content":"修改"}}]}',
        "data: [DONE]",
    ])
    r = client.post("/api/v1/llm/chat", json={"messages": [{"role": "user", "content": "改短一点"}]})
    assert r.status_code == 200
    assert "text/event-stream" in r.content_type
    body = r.get_data(as_text=True)
    assert '"chunk": "可以"' in body
    assert '"done": true' in body


def test_api_chat_sanitizes_roles(client, monkeypatch):
    """非法角色被归一为 user，超长历史截断。"""
    _configured()
    seen = {}
    orig = llm.chat_stream

    def spy(messages, *a, **kw):
        seen["messages"] = messages
        return orig(messages, *a, **kw)

    monkeypatch.setattr(llm, "chat_stream", spy)
    _mock_stream(monkeypatch, ['data: {"choices":[{"delta":{"content":"ok"}}]}', "data: [DONE]"])
    msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}] + [
        {"role": "user", "content": f"m{i}"} for i in range(30)
    ]
    client.post("/api/v1/llm/chat", json={"messages": msgs})
    roles = [m["role"] for m in seen["messages"]]
    assert "system" not in roles
    assert len(seen["messages"]) <= 20


def test_api_chat_requires_messages(client):
    r = client.post("/api/v1/llm/chat", json={"messages": []})
    assert r.status_code == 400


# ---------------- 模型列表 ----------------

def _mock_models_get(monkeypatch, payload):
    calls = []

    def fake_get(url, headers, timeout=20):
        calls.append({"url": url, "headers": headers})
        return payload

    monkeypatch.setattr(llm, "_http_get", fake_get)
    return calls


def test_list_models_openai(monkeypatch):
    _configured()
    calls = _mock_models_get(monkeypatch, {"data": [
        {"id": "gpt-4o-mini"}, {"id": "gpt-4o"}, {"id": "deepseek-chat"}]})
    r = llm.list_models()
    ids = [m["id"] for m in r["models"]]
    assert "gpt-4o-mini" in ids and "deepseek-chat" in ids
    assert calls[0]["url"] == "https://api.example.com/models"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"


def test_list_models_current_first(monkeypatch):
    """当前配置的模型排在最前。"""
    _configured(model="gpt-4o")
    _mock_models_get(monkeypatch, {"data": [{"id": "aaa"}, {"id": "gpt-4o"}, {"id": "zzz"}]})
    r = llm.list_models()
    assert r["models"][0]["id"] == "gpt-4o"


def test_list_models_anthropic(monkeypatch):
    _configured(format="anthropic")
    calls = _mock_models_get(monkeypatch, {"data": [
        {"id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5"}]})
    r = llm.list_models()
    assert r["models"][0]["name"] == "Claude Sonnet 4.5"
    assert calls[0]["url"].endswith("/v1/models")
    assert calls[0]["headers"]["x-api-key"] == "sk-test"
    assert "anthropic-version" in calls[0]["headers"]


def test_list_models_gemini(monkeypatch):
    _configured(format="gemini")
    calls = _mock_models_get(monkeypatch, {"models": [
        {"name": "models/gemini-2.0-flash", "displayName": "Gemini 2.0 Flash"}]})
    r = llm.list_models()
    assert r["models"][0]["id"] == "gemini-2.0-flash"   # 去掉 models/ 前缀
    assert r["models"][0]["name"] == "Gemini 2.0 Flash"
    assert "key=sk-test" in calls[0]["url"]


def test_list_models_azure(monkeypatch):
    _configured(format="azure")
    calls = _mock_models_get(monkeypatch, {"data": [{"id": "my-gpt4-deployment"}]})
    r = llm.list_models()
    assert r["models"][0]["id"] == "my-gpt4-deployment"
    assert "/openai/deployments" in calls[0]["url"]
    assert calls[0]["headers"]["api-key"] == "sk-test"


def test_list_models_unconfigured():
    import pytest

    with pytest.raises(ValueError, match="尚未配置"):
        llm.list_models()


def test_list_models_empty(monkeypatch):
    import pytest

    _configured()
    _mock_models_get(monkeypatch, {"data": []})
    with pytest.raises(RuntimeError, match="空的模型列表"):
        llm.list_models()


def test_list_models_http_error(monkeypatch):
    import urllib.error

    _configured()

    def boom(url, headers, timeout=20):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(llm, "_http_get", boom)
    with pytest.raises(RuntimeError, match="API Key 无效"):
        llm.list_models()


def test_api_list_models(client, monkeypatch):
    _configured()
    _mock_models_get(monkeypatch, {"data": [{"id": "m1"}, {"id": "m2"}]})
    r = client.get("/api/v1/llm/models")
    assert r.status_code == 200
    assert [m["id"] for m in r.get_json()["models"]] == ["m1", "m2"]


def test_api_list_models_unconfigured(client):
    r = client.get("/api/v1/llm/models")
    assert r.status_code == 400


# ---------------- 配置保存：部分填写不再 400 ----------------

def test_config_allows_missing_model(client):
    """只填 base_url + key（模型名空）也应保存成功——不再 400 拒绝。

    历史 bug：用户填了 Key 但没选预设（模型名为空）→ PUT 400 → 配置从不落盘
    → 报「尚未配置」且下次打开要重填。
    """
    r = client.put("/api/v1/llm/config", json={
        "base_url": "https://api.deepseek.com", "api_key": "sk-x", "model": ""})
    assert r.status_code == 200
    body = r.get_json()
    assert body["base_url"] == "https://api.deepseek.com"
    assert body["has_key"] is True
    assert body["configured"] is False          # 缺模型 → 未配置，但已保存
    # 重新打开（GET）应保留已填内容
    again = client.get("/api/v1/llm/config").get_json()
    assert again["base_url"] == "https://api.deepseek.com"
    assert again["has_key"] is True


def test_config_still_rejects_empty_base_url(client):
    r = client.put("/api/v1/llm/config", json={"base_url": "", "model": "m"})
    assert r.status_code == 400


# ---------------- 多配置管理 ----------------

def test_configs_migration_from_legacy(tmp_path):
    """旧版 llm_config.json 自动迁移为「默认配置」。"""
    tmp_path.joinpath("llm_config.json").write_text(
        '{"base_url": "https://api.deepseek.com", "api_key": "sk-old", "model": "deepseek-chat"}',
        encoding="utf-8")
    data = llm.load_configs()
    assert len(data["configs"]) == 1
    assert data["configs"][0]["name"] == "默认配置"
    assert data["active"] == data["configs"][0]["id"]
    assert llm.load_config()["model"] == "deepseek-chat"


def test_create_and_list_configs(isolated_config):
    cfg = llm.create_config({"name": "我的 DeepSeek", "base_url": "https://api.deepseek.com",
                             "api_key": "sk-a", "model": "deepseek-chat"})
    assert cfg["name"] == "我的 DeepSeek"
    pub = llm.public_configs()
    assert any(c["name"] == "我的 DeepSeek" for c in pub["configs"])
    assert pub["active"] == cfg["id"]
    # 列表不含 key
    assert "sk-a" not in json.dumps(pub)


def test_create_second_config_activates_it(isolated_config):
    c1 = llm.create_config({"name": "配置一", "base_url": "https://a.com", "api_key": "k1", "model": "m1"})
    c2 = llm.create_config({"name": "配置二", "base_url": "https://b.com", "api_key": "k2", "model": "m2"})
    assert llm.public_configs()["active"] == c2["id"]
    assert llm.load_config()["model"] == "m2"
    # 切回配置一
    assert llm.activate_config(c1["id"])
    assert llm.load_config()["model"] == "m1"


def test_update_config_name(isolated_config):
    cfg = llm.create_config({"name": "旧名", "base_url": "https://a.com", "api_key": "k", "model": "m"})
    llm.update_config(cfg["id"], {"name": "新名字"})
    pub = llm.public_configs()
    cur = next(c for c in pub["configs"] if c["id"] == cfg["id"])
    assert cur["name"] == "新名字"
    # 其他字段保留
    assert cur["model"] == "m"


def test_delete_config(isolated_config):
    c1 = llm.create_config({"name": "保留", "base_url": "https://a.com", "api_key": "k1", "model": "m1"})
    c2 = llm.create_config({"name": "删除", "base_url": "https://b.com", "api_key": "k2", "model": "m2"})
    assert llm.delete_config(c2["id"])
    pub = llm.public_configs()
    names = [c["name"] for c in pub["configs"]]
    assert "删除" not in names and "保留" in names
    # 删的是激活配置 → active 仍指向一套有效配置
    assert pub["active"] in [c["id"] for c in pub["configs"]]
    assert not llm.delete_config("nonexistent")


def test_save_config_updates_active(isolated_config):
    """旧接口 PUT /config 语义：更新当前激活配置。"""
    c1 = llm.create_config({"name": "A", "base_url": "https://a.com", "api_key": "k1", "model": "m1"})
    llm.create_config({"name": "B", "base_url": "https://b.com", "api_key": "k2", "model": "m2"})
    llm.save_config({"base_url": "https://c.com", "model": "m3", "name": "B 改名"})
    assert llm.load_config()["model"] == "m3"
    assert llm.load_config()["base_url"] == "https://c.com"
    pub = llm.public_configs()
    b = next(c for c in pub["configs"] if c["id"] == llm.public_config()["id"])
    assert b["name"] == "B 改名"
    # A 不受影响
    a = next(c for c in pub["configs"] if c["id"] == c1["id"])
    assert a["model"] == "m1"


def test_api_configs_endpoints(client):
    # 列表（初始含迁移出的默认配置）
    r = client.get("/api/v1/llm/configs")
    assert r.status_code == 200
    body = r.get_json()
    assert body["configs"] and "active" in body

    # 新建（自定义名称）
    r = client.post("/api/v1/llm/configs", json={
        "name": "API 测试配置", "base_url": "https://api.example.com",
        "api_key": "sk-api", "model": "m1"})
    assert r.status_code == 200
    new_id = r.get_json()["config"]["id"]
    assert r.get_json()["configs"]["active"] == new_id

    # 改名
    r = client.put(f"/api/v1/llm/configs/{new_id}", json={"name": "改名后"})
    assert r.status_code == 200
    assert r.get_json()["config"]["name"] == "改名后"

    # 激活（新建另一套后切回）
    r2 = client.post("/api/v1/llm/configs", json={
        "name": "另一套", "base_url": "https://api2.example.com", "api_key": "sk2", "model": "m2"})
    other_id = r2.get_json()["config"]["id"]
    r = client.post(f"/api/v1/llm/configs/{new_id}/activate")
    assert r.status_code == 200
    assert r.get_json()["configs"]["active"] == new_id
    assert client.get("/api/v1/llm/config").get_json()["model"] == "m1"

    # 删除
    r = client.delete(f"/api/v1/llm/configs/{other_id}")
    assert r.status_code == 200
    assert client.delete("/api/v1/llm/configs/nonexistent").status_code == 404


def test_api_create_config_blank_ok(client):
    """新建允许全空（用户在设置页补全），仅 URL 格式错才拒。"""
    r = client.post("/api/v1/llm/configs", json={"name": "x"})
    assert r.status_code == 200
    r = client.post("/api/v1/llm/configs", json={"name": "x", "base_url": "ftp://bad"})
    assert r.status_code == 400


def test_api_configs_never_leak_key(client):
    r = client.post("/api/v1/llm/configs", json={
        "name": "泄漏检查", "base_url": "https://api.example.com", "api_key": "sk-secret-123", "model": "m"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "sk-secret-123" not in body
