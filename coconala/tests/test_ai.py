import json
from pathlib import Path
from types import SimpleNamespace

from app.ai import REVIEW_SCHEMA, AIReviewer, build_job_prompt
from app.config import load_config
from app.score import evaluate

CFG = load_config(Path(__file__).resolve().parent.parent / "config.yaml")

REVIEW = {
    "fit_score": 90, "matched_category": "米国・NY市場調査、海外リサーチ", "estimated_hours": 6,
    "clarity_score": 80, "revision_risk": "低", "red_flags": [], "recommend": "応募する",
    "reason": "NY在住の強みが生きる", "suggested_price_yen": 25000, "suggested_delivery_days": 5,
    "questions_for_client": ["調査の目的"], "proposal": "はじめまして。",
}


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_client(text, stop_reason="end_turn"):
    response = SimpleNamespace(stop_reason=stop_reason, content=[
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=text),
    ])
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def job():
    j = {
        "id": "1", "url": "u", "title": "NYの市場調査", "breadcrumb": "", "proposals": 2, "days_left": 3,
        "delivery_date": None, "closed": False, "page_text": "",
        "description": "マンハッタンの日本食レストランを調べてください。" * 5,
        "budget": {"min": 10000, "max": 30000, "label": "10,000円〜30,000円", "type": "fixed"},
    }
    return evaluate(j, CFG)


def test_request_shape_and_parse():
    client, messages = fake_client(json.dumps(REVIEW, ensure_ascii=False))
    reviewer = AIReviewer(CFG, "プロフィール本文", client=client)
    assert reviewer.review(job()) == REVIEW

    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["schema"] is REVIEW_SCHEMA
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "プロフィール本文" in call["system"][0]["text"]
    assert "マンハッタン" in call["messages"][0]["content"]


def test_schema_lists_every_property_as_required():
    assert set(REVIEW_SCHEMA["required"]) == set(REVIEW_SCHEMA["properties"])
    assert REVIEW_SCHEMA["additionalProperties"] is False


def test_refusal_or_bad_json_returns_none():
    client, _ = fake_client("", stop_reason="refusal")
    assert AIReviewer(CFG, "p", client=client).review(job()) is None
    client, _ = fake_client("not json")
    assert AIReviewer(CFG, "p", client=client).review(job()) is None


def test_prompt_uses_page_text_when_description_missing():
    j = job()
    j["description"] = ""
    j["page_text"] = "ページ全体のテキスト"
    assert "ページ全体のテキスト" in build_job_prompt(j)


def test_process_uses_ai_result(monkeypatch):
    import anthropic

    import coconala

    client, _ = fake_client(json.dumps(REVIEW, ensure_ascii=False))
    monkeypatch.setattr(anthropic, "Anthropic", lambda: client)
    j = job()
    del j["eval"]
    [result] = coconala.process([j], CFG, use_ai=True)
    assert result["proposal"] == "はじめまして。"
    assert result["eval"]["source"] == "ai" and result["eval"]["price"] == 25000
    assert result["eval"]["ai_recommend"] == "応募する"
