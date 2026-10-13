from pathlib import Path

import pytest

from app.config import load_config
from app.score import _match, apply_ai_review, evaluate, find_avoid_reasons, sort_jobs, suggest_price

CFG = load_config(Path(__file__).resolve().parent.parent / "config.yaml")


def make_job(title, description, budget=None, proposals=3, **extra):
    job = {
        "id": extra.pop("id", "1"), "url": "u", "title": title, "description": description,
        "breadcrumb": extra.pop("breadcrumb", ""),
        "budget": budget or {"min": 10000, "max": 30000, "label": "10,000円〜30,000円", "type": "fixed"},
        "proposals": proposals, "days_left": 5, "delivery_date": None, "closed": False, "page_text": "",
    }
    job.update(extra)
    return job


LONG = "目的や納品の形も書いてある、十分な長さの依頼本文です。" * 4


def test_match_english_words_need_boundaries():
    assert _match("PR戦略を考えてほしい", "PR")
    assert not _match("PRODUCTの紹介", "PR")
    assert _match("NYの市場", "NY")
    assert not _match("COMPANY", "NY")
    assert _match("詳しくはLINEで連絡", "LINEで")
    assert not _match("ONLINEで開催", "LINEで")
    assert _match("報酬は0円です", "re:(?<![\\d,])0円") == "0円"
    assert not _match("10,000円", "re:(?<![\\d,])0円")


@pytest.mark.parametrize("text, group", [
    ("今回は無償でお願いします", "無報酬"),
    ("修正回数は無制限でお願いします", "修正が多すぎる"),
    ("詳しくはLINEで連絡ください", "ココナラ外への誘導・あやしい案件"),
])
def test_avoid(text, group):
    reasons = find_avoid_reasons(make_job("調査", text + LONG), CFG)
    assert any(r.startswith(group) for r in reasons)


def test_unclear_short_description():
    reasons = find_avoid_reasons(make_job("調査", "詳細はメッセージで"), CFG)
    assert any("内容が不明確" in r for r in reasons)


def test_low_budget():
    job = make_job("市場調査", LONG, budget={"min": None, "max": 1000, "label": "〜1,000円", "type": "fixed"})
    assert any("予算が低い" in r for r in find_avoid_reasons(job, CFG))


def test_ranking_prefers_fit_and_pay():
    ny = evaluate(make_job("アメリカの市場調査（NY）", LONG, id="ny"), CFG)
    jp = evaluate(make_job("英語メールの翻訳 500文字", "英語のメールを日本語に翻訳してください。" * 3, id="tr",
                           budget={"min": 3000, "max": 5000, "label": "3,000円〜5,000円", "type": "fixed"}), CFG)
    logo = evaluate(make_job("ロゴデザイン", "カフェのロゴを作ってください。色は緑系です。" * 3, id="logo"), CFG)
    order = [j["id"] for j in sort_jobs([logo, jp, ny])]
    assert order[0] == "ny"
    assert logo["eval"]["excluded"]  # スキルに合わない
    assert ny["eval"]["category"] == "米国・NY市場調査、海外リサーチ"
    assert jp["eval"]["hours"] < 2  # 500文字の翻訳は短時間


def test_price_stays_in_budget():
    job = make_job("市場調査", LONG, budget={"min": 5000, "max": 8000, "label": "", "type": "fixed"})
    assert 5000 <= suggest_price(job, 10, CFG) <= 8000
    assert suggest_price(job, 0.5, CFG) == 5000


def test_ai_review_overrides_and_can_exclude():
    job = evaluate(make_job("アメリカの市場調査", LONG), CFG)
    review = {
        "fit_score": 20, "matched_category": "", "estimated_hours": 40, "clarity_score": 30,
        "revision_risk": "高", "red_flags": ["作業量が多い"], "recommend": "見送り",
        "reason": "作業量に対して予算が少ない", "suggested_price_yen": 30000,
        "suggested_delivery_days": 14, "questions_for_client": [], "proposal": "",
    }
    apply_ai_review(job, review, CFG)
    ev = job["eval"]
    assert ev["source"] == "ai"
    assert ev["parts"]["fit"] == 20 and ev["parts"]["clarity"] == 10
    assert ev["hours"] == 40
    assert any("AI判定" in r for r in ev["excluded"])


def test_hourly_job():
    job = make_job("英語の翻訳（継続）", LONG,
                   budget={"min": 1500, "max": None, "label": "時給 1,500円〜", "type": "hourly"})
    evaluate(job, CFG)
    assert job["eval"]["hourly_net"] == 1170
    assert job["eval"]["price"] == 3900  # 目標時給3,000円 ÷ (1 - 0.22) を100円単位で切り上げ
