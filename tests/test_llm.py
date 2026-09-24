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


def _mock_chat(monkeypatch, reply: str):
    """mock _http_post，返回指定的 assistant 内容；记录调用参数。"""
    calls = []

    def fake_post(url, headers, payload, timeout):
        calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return {"choices": [{"message": {"content": reply}}]}

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
    path = llm._config_path()
    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["api_key"] == "sk-test"  # 落盘在 gitignored 的 data/ 下


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
