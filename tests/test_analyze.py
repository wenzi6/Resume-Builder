"""JD 关键词匹配回归（纯本地，不依赖 LLM）。"""
from __future__ import annotations

from resume_builder.sample import sample_general
from resume_builder.services import analyze

JD_FRONTEND = """
岗位职责：
1. 负责公司核心产品的前端架构设计与开发，精通 React、TypeScript；
2. 参与前端性能优化，熟悉 Webpack、Vite 构建工具；
3. 与后端协作完成接口联调，了解 Node.js；
4. 本科及以上学历，计算机相关专业；
5. 具备良好的沟通能力和团队协作精神。
"""


def test_extract_keywords():
    kw = analyze.extract_keywords(JD_FRONTEND)
    assert "React" in kw["skill"]
    assert "TypeScript" in kw["skill"]
    assert "Webpack" in kw["skill"]
    assert "本科" in kw["education"]
    assert "前端" in kw["position"]
    assert "沟通" in kw["soft"]


def test_extract_keywords_empty():
    kw = analyze.extract_keywords("")
    assert all(v == [] for v in kw.values())


def test_analyze_match_rate(sample_general=None):
    from resume_builder.sample import sample_general as sg

    doc = sg()
    doc["content"]["skills"]["featuredSkills"] = [
        {"skill": "React", "rating": 5},
        {"skill": "Vue", "rating": 4},
        {"skill": "TypeScript", "rating": 4},
    ]
    r = analyze.analyze(doc, JD_FRONTEND)
    assert 0 <= r["score"] <= 100
    assert r["score"] >= 60, r["score"]  # 示例简历与前端 JD 匹配度应较高
    assert r["matchedCount"] > 0
    assert any(m["keyword"] == "React" for m in r["matched"])


def test_analyze_missing_keywords():
    from resume_builder.sample import sample_general as sg

    doc = sg()
    r = analyze.analyze(doc, "要求精通 Rust 与 Solidity，熟悉区块链底层原理")
    missing_kw = [m["keyword"] for m in r["missing"]]
    assert "Rust" in missing_kw
    assert r["score"] < 60
    assert any("Rust" in s for s in r["suggestions"])


def test_analyze_requires_jd():
    import pytest

    from resume_builder.sample import sample_general as sg

    with pytest.raises(ValueError, match="JD"):
        analyze.analyze(sg(), "  ")


def test_analyze_jd_too_long():
    import pytest

    from resume_builder.sample import sample_general as sg

    with pytest.raises(ValueError, match="过长"):
        analyze.analyze(sg(), "岗" * 8001)


def test_api_analyze(client):
    from resume_builder.sample import sample_general as sg

    r = client.post("/api/v1/analyze", json={"document": sg(), "jd": JD_FRONTEND})
    assert r.status_code == 200
    body = r.get_json()
    assert "score" in body and "missing" in body and "suggestions" in body
    assert body["score"] > 0


def test_api_analyze_requires_document(client):
    r = client.post("/api/v1/analyze", json={"jd": "x"})
    assert r.status_code == 400
