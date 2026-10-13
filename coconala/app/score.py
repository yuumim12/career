"""② 案件の選別 と ③ 優先順位付け（ルールでの評価）。

点数はすべて 0〜100。最後に config.yaml の score_weights で合計点を出す。
"""
from __future__ import annotations

import math
import re


def _match(text: str, phrase: str) -> str | None:
    """phrase が text に入っていれば、見つかった文字列を返す。

    "re:" で始まるものは正規表現。英字で始まる/終わる言葉は、単語の途中では数えない
    （「PR」が「PRODUCT」に、「LINEで」が「ONLINEで」に当たらないように）。
    """
    if phrase.startswith("re:"):
        pattern = phrase[3:]
    else:
        pattern = re.escape(phrase)
        if re.match(r"[A-Za-z]", phrase):
            pattern = r"(?<![A-Za-z])" + pattern
        if re.search(r"[A-Za-z]$", phrase):
            pattern += r"(?![A-Za-z])"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(0) if m else None


def _contains(text: str, phrase: str) -> bool:
    return _match(text, phrase) is not None


def find_avoid_reasons(job: dict, cfg: dict) -> list[str]:
    """避ける案件に当てはまる理由のリスト（空なら問題なし）。"""
    text = f"{job['title']}\n{job['description']}"
    reasons = []
    for group, phrases in (cfg.get("avoid") or {}).items():
        hits = [h for h in (_match(text, p) for p in phrases) if h]
        if hits:
            reasons.append(f"{group}（「{hits[0]}」）")

    desc_len = len(job["description"])
    min_len = cfg.get("min_description_chars", 60)
    unclear = [p for p in cfg.get("unclear_phrases", []) if p in text]
    if desc_len < min_len:
        reasons.append(f"内容が不明確（本文が{desc_len}文字だけ）")
    elif unclear and desc_len < 300:
        reasons.append(f"内容が不明確（「{unclear[0]}」で本文が短い）")

    b = job["budget"]
    if b["type"] in ("fixed", "hourly") and b["max"] is not None:
        limit = cfg.get("min_budget_yen", 3000) if b["type"] == "fixed" else 1000
        if b["max"] < limit:
            reasons.append(f"予算が低い（上限{b['max']:,}円）")

    if job.get("closed"):
        reasons.append("募集が終わっている")
    elif job.get("days_left") is not None and job["days_left"] < 0:
        reasons.append("締め切りを過ぎている")
    return reasons


def match_categories(job: dict, cfg: dict) -> list[dict]:
    """得意分野ごとの合い方。タイトルに入っていたら2点、本文・カテゴリなら1点。"""
    title = job["title"]
    body = f"{job['breadcrumb']}\n{job['description']}"
    results = []
    for cat in cfg.get("categories", []):
        points, hits = 0, []
        for kw in cat.get("keywords", []):
            if _contains(title, kw):
                points += 2
                hits.append(kw)
            elif _contains(body, kw):
                points += 1
                hits.append(kw)
        strength = min(1.0, points / 4)
        results.append({
            "name": cat["name"],
            "score": round(cat.get("weight", 50) * strength),
            "hours": cat.get("hours", 6),
            "hits": hits,
        })
    return sorted(results, key=lambda r: r["score"], reverse=True)


def fit_score(job: dict, cfg: dict) -> tuple[int, list[dict], list[str]]:
    cats = match_categories(job, cfg)
    best = cats[0] if cats else {"score": 0}
    extra = sum(1 for c in cats[1:] if c["score"] >= 30)  # 複数の分野に合うと少し加点
    score = min(100, best["score"] + 5 * extra)
    notes = []
    text = f"{job['title']}\n{job['description']}"
    for c in cfg.get("caution", []):
        if c["phrase"] in text:
            score -= 10
            notes.append(f"注意: {c['note']}")
    return max(0, score), cats, notes


def estimate_hours(job: dict, best_cat: dict | None, cfg: dict) -> float:
    """作業時間の目安（やりとりの時間も含めたざっくりの数字）。"""
    hours = float(best_cat["hours"]) if best_cat else 6.0
    text = f"{job['title']}\n{job['description']}"
    is_text_work = re.search(r"翻訳|英訳|和訳|ライティング|記事|執筆|文字起こし", text)

    chars = re.search(r"(\d[\d,]*)\s*(?:文字|字)", text)
    words = re.search(r"(\d[\d,]*)\s*(?:words?|ワード|語)", text, re.I)
    pages = re.search(r"(\d+)\s*(?:ページ|枚|スライド)", text)
    if is_text_work and chars:
        hours = int(chars.group(1).replace(",", "")) / cfg.get("chars_per_hour", 1200) + 0.5
    elif is_text_work and words:
        hours = int(words.group(1).replace(",", "")) / cfg.get("words_per_hour", 400) + 0.5
    elif pages:
        hours = max(hours * 0.5, int(pages.group(1)) * 0.75)

    if re.search(r"簡単|短時間|すぐ終わる|軽作業|1時間程度|30分", text):
        hours *= 0.6
    if re.search(r"大量|長期|毎月|網羅|全国|すべての", text):
        hours *= 1.5
    return round(min(max(hours, 0.5), 80), 1)


def pay_info(job: dict, hours: float, cfg: dict) -> tuple[int, float | None, str]:
    """(点数, 手取りの時給, 説明)。"""
    b = job["budget"]
    fee = cfg.get("fee_rate", 0.22)
    target = cfg.get("target_hourly_yen", 3000)
    if b["type"] == "hourly" and (b["min"] or b["max"]):
        rate = (b["min"] + b["max"]) / 2 if (b["min"] and b["max"]) else (b["max"] or b["min"])
        hourly = rate * (1 - fee)
        return min(100, round(hourly / target * 100)), round(hourly), "時給の案件"
    if b["type"] == "monthly":
        return 50, None, "月額の案件（時給は、作業時間を聞いてから計算）"
    if b["type"] == "fixed" and (b["min"] or b["max"]):
        amount = (b["min"] + b["max"]) / 2 if (b["min"] and b["max"]) else (b["max"] or b["min"])
        hourly = amount * (1 - fee) / hours
        return min(100, round(hourly / target * 100)), round(hourly), ""
    if b["type"] == "quote":
        return 55, None, "予算は見積り希望（金額をこちらで出せる）"
    return 40, None, "予算がわからない"


def win_score(job: dict) -> int:
    n = job.get("proposals")
    if n is None:
        return 50
    for limit, score in ((2, 100), (5, 80), (10, 60), (20, 40)):
        if n <= limit:
            return score
    return 20


def clarity_score(job: dict, cfg: dict) -> int:
    n = len(job["description"])
    score = 20 if n < 80 else 50 if n < 200 else 75 if n < 400 else 90
    if job["budget"]["type"] in ("fixed", "hourly"):
        score += 5
    if job.get("delivery_date"):
        score += 5
    if any(p in job["description"] for p in cfg.get("unclear_phrases", [])):
        score -= 30
    return max(0, min(100, score))


def total_score(parts: dict, cfg: dict) -> int:
    w = cfg.get("score_weights", {"fit": 0.4, "pay": 0.3, "win": 0.2, "clarity": 0.1})
    return round(sum(parts[k] * w.get(k, 0) for k in ("fit", "pay", "win", "clarity")))


def rank_label(total: int, cfg: dict) -> str:
    if total >= cfg.get("rank_a", 70):
        return "A"
    if total >= cfg.get("rank_b", 55):
        return "B"
    return "C"


def suggest_price(job: dict, hours: float, cfg: dict) -> int:
    """目標の時給から逆算した提案金額（予算の範囲に合わせる。500円単位）。"""
    fee = cfg.get("fee_rate", 0.22)
    b = job["budget"]
    if b["type"] == "hourly":  # 時給の案件は、時給の金額を出す（100円単位）
        rate = math.ceil(cfg.get("target_hourly_yen", 3000) / (1 - fee) / 100) * 100
        if b["max"]:
            rate = min(rate, b["max"])
        if b["min"]:
            rate = max(rate, b["min"])
        return int(rate)
    price = hours * cfg.get("target_hourly_yen", 3000) / (1 - fee)
    if b["type"] == "fixed":
        if b["max"]:
            price = min(price, b["max"])
        if b["min"]:
            price = max(price, b["min"])
    return int(max(1000, math.ceil(price / 500) * 500))


def suggest_days(job: dict, hours: float, cfg: dict) -> int:
    days = math.ceil(hours / cfg.get("hours_per_day", 3)) + 1
    return max(2, days)


def evaluate(job: dict, cfg: dict) -> dict:
    """1つの案件を評価して、job["eval"] に結果を入れる。"""
    fit, cats, notes = fit_score(job, cfg)
    best = cats[0] if cats and cats[0]["score"] > 0 else None
    hours = estimate_hours(job, best, cfg)
    pay, hourly, pay_note = pay_info(job, hours, cfg)
    parts = {"fit": fit, "pay": pay, "win": win_score(job), "clarity": clarity_score(job, cfg)}
    total = total_score(parts, cfg)

    excluded = find_avoid_reasons(job, cfg)
    if fit < cfg.get("min_fit", 35):
        excluded.append(f"スキルとの重なりが少ない（{fit}点）")

    reasons = []
    if best:
        reasons.append(f"分野: {best['name']}（{', '.join(best['hits'][:4])}）")
    if hourly:
        reasons.append(f"手取り時給の目安: {hourly:,}円（{hours}時間で計算）")
    if pay_note:
        reasons.append(pay_note)
    if job.get("proposals") is not None:
        reasons.append(f"提案数: {job['proposals']}件")
    reasons.extend(notes)

    job["eval"] = {
        "source": "rule",
        "parts": parts,
        "total": total,
        "rank": rank_label(total, cfg),
        "category": best["name"] if best else "",
        "hours": hours,
        "hourly_net": hourly,
        "price": suggest_price(job, hours, cfg),
        "days": suggest_days(job, hours, cfg),
        "reasons": reasons,
        "excluded": excluded,
    }
    return job


def apply_ai_review(job: dict, review: dict, cfg: dict) -> dict:
    """AIの評価で、合い方・時間・わかりやすさを上書きして、点数を出し直す。"""
    ev = job["eval"]
    hours = max(0.5, float(review["estimated_hours"]))
    pay, hourly, _ = pay_info(job, hours, cfg)
    clarity = int(review["clarity_score"])
    if review["revision_risk"] == "高":
        clarity = max(0, clarity - 20)
    clamp = lambda v: max(0, min(100, int(v)))  # noqa: E731
    clarity = clamp(clarity)
    parts = {"fit": clamp(review["fit_score"]), "pay": pay, "win": ev["parts"]["win"], "clarity": clarity}
    total = total_score(parts, cfg)
    ev.update({
        "source": "ai",
        "parts": parts,
        "total": total,
        "rank": rank_label(total, cfg),
        "category": review["matched_category"] or ev["category"],
        "hours": round(hours, 1),
        "hourly_net": hourly,
        "price": int(review["suggested_price_yen"]) or ev["price"],
        "days": int(review["suggested_delivery_days"]) or ev["days"],
        "ai_recommend": review["recommend"],
        "ai_reason": review["reason"],
        "ai_red_flags": review["red_flags"],
        "revision_risk": review["revision_risk"],
        "questions": review["questions_for_client"],
    })
    if review["recommend"] == "見送り":
        ev["excluded"] = ev["excluded"] + [f"AI判定: {review['reason']}"]
    return job


def sort_jobs(jobs: list[dict]) -> list[dict]:
    return sorted(jobs, key=lambda j: (bool(j["eval"]["excluded"]), -j["eval"]["total"]))
