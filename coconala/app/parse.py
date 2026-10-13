"""案件ページから読み取ったテキストを、予算・提案数・期限などに分ける。

ココナラの画面のデザインが変わっても動くように、HTMLの細かい形ではなく
「予算」「提案数」などの見出しの言葉を手がかりにしている。
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime

# 「5,000円」「5千円」「1.5万円」「1万」など。万・千・円のどれかが付いた数字だけを金額とみなす
AMOUNT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(万|千)?\s*(円)?")
RANGE_SEP = re.compile(r"[〜～~\-－ー–—]|から")


def to_yen(number: str, unit: str | None) -> int:
    value = float(number.replace(",", ""))
    if unit == "万":
        value *= 10000
    elif unit == "千":
        value *= 1000
    return int(round(value))


def _amounts(text: str) -> list[tuple[int, int, int]]:
    """(金額, 開始位置, 終了位置) のリスト。"""
    found = []
    for m in AMOUNT.finditer(text):
        if not (m.group(2) or m.group(3)):
            continue
        found.append((to_yen(m.group(1), m.group(2)), m.start(), m.end()))
    return found


def _after_label(text: str, label_pattern: str, lines: int = 2) -> list[str]:
    """見出しの後ろにある文字列（同じ行の残り＋次の行など）を、見つかった数だけ返す。"""
    results = []
    for m in re.finditer(label_pattern, text):
        rest = text[m.end():]
        rest = rest.lstrip(" \t:：")
        chunk = [ln.strip() for ln in rest.split("\n")[: lines + 1]]
        chunk = [c for c in chunk if c][:lines]
        results.append(" ".join(chunk))
    return results


QUOTE = {"min": None, "max": None, "label": "見積り希望", "type": "quote"}
# 見出しのすぐ後ろに値がある形（「予算 5,000円」「予算：見積り希望」）。本文の中の「予算は〜」と区別する
DIRECT_VALUE = re.compile(r"\s*([\d〜～~]|見積|未定|相談|応相談|時給|月給|月額|時間単価)")


def _budget_from_window(window: str) -> dict | None:
    head = window[:40]
    if re.match(r"\s*(見積|未定|相談|応相談)", head):
        return dict(QUOTE)
    amounts = _amounts(head)
    if not amounts:
        return None
    pay_type = "fixed"
    if re.search(r"時給|/\s*時間?|時間単価", head):
        pay_type = "hourly"
    elif re.search(r"月給|/\s*月|月額", head):
        pay_type = "monthly"

    first = amounts[0]
    # 範囲：「10,000円 〜 30,000円」「5千〜1万円」
    if len(amounts) >= 2 and RANGE_SEP.search(head[first[2]: amounts[1][1]]):
        lo, hi = first[0], amounts[1][0]
        return {"min": min(lo, hi), "max": max(lo, hi), "label": head[: amounts[1][2]].strip(), "type": pay_type}
    label = head[: first[2]].strip()
    before = head[: first[1]]
    after = head[first[2]: first[2] + 2]
    if before and RANGE_SEP.search(before[-2:]):  # 〜5,000円
        return {"min": None, "max": first[0], "label": label, "type": pay_type}
    if RANGE_SEP.match(after.strip()):  # 5,000円〜
        return {"min": first[0], "max": None, "label": label + after.strip()[:1], "type": pay_type}
    return {"min": first[0], "max": first[0], "label": label, "type": pay_type}


def parse_budget(text: str) -> dict:
    """予算を読む。戻り値: {"min", "max", "label", "type"}。type は fixed / hourly / monthly / quote / unknown。"""
    windows = _after_label(text, r"予算", lines=2)
    direct = [w for w in windows if DIRECT_VALUE.match(w)]
    for group in (direct, windows):
        for window in group:
            result = _budget_from_window(window)
            if result:
                return result
    if any(re.search(r"見積|未定|相談", w[:40]) for w in windows):
        return dict(QUOTE)
    return {"min": None, "max": None, "label": "不明", "type": "unknown"}


def parse_proposals(text: str) -> int | None:
    patterns = [
        r"提案数\s*[:：]?\s*\n?\s*(\d+)",
        r"提案\s*[:：]?\s*(\d+)\s*(?:件|人|名)",
        r"(\d+)\s*(?:件|人|名)\s*(?:の|が)?提案",
        r"応募(?:者|数)\s*[:：]?\s*\n?\s*(\d+)",
        r"(\d+)\s*(?:人|名)が応募",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return int(m.group(1))
    return None


DATE = re.compile(r"(\d{4})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})")


def _first_date(s: str) -> date | None:
    m = DATE.search(s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_days_left(text: str, today: date) -> int | None:
    """募集の締め切りまで、あと何日か。"""
    if re.search(r"本日(締切|締め切り|まで)", text):
        return 0
    for window in _after_label(text, r"(募集期限|募集期間|締切|締め切り|応募期限)", lines=2):
        m = re.search(r"あと\s*(\d+)\s*日", window)
        if m:
            return int(m.group(1))
        if re.search(r"あと\s*\d+\s*時間", window):
            return 0
        d = _first_date(window)
        if d:
            return (d - today).days
    m = re.search(r"(?:締切|締め切り)まで\s*(?:あと)?\s*(\d+)\s*日", text)
    if m:
        return int(m.group(1))
    return None


def parse_label_date(text: str, label_pattern: str) -> date | None:
    for window in _after_label(text, label_pattern, lines=2):
        d = _first_date(window)
        if d:
            return d
    return None


def is_closed(text: str) -> bool:
    if re.search(r"(募集|受付)(は|を)?(終了し|締め切られ|締め切り)ました", text):
        return True
    # 「募集終了」だけの行（状態の表示）。「募集終了した案件を見る」のようなリンクは数えない
    return any(line.strip() == "募集終了" for line in text.split("\n"))


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def _from_json_ld(blocks: list[str]) -> dict:
    """構造化データ（JSON-LD）があれば、タイトル・本文・パンくずを取る。"""
    out: dict = {}
    items: list = []
    for raw in blocks:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and "@graph" in data:
            data = data["@graph"]
        items.extend(data if isinstance(data, list) else [data])
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("@type")
        if kind == "JobPosting":
            out["title"] = item.get("title") or ""
            out["description"] = _strip_html(item.get("description") or "")
            if item.get("datePosted"):
                out["posted"] = str(item["datePosted"])[:10]
            if item.get("validThrough"):
                out["valid_through"] = str(item["validThrough"])[:10]
        elif kind == "BreadcrumbList":
            names = []
            for el in item.get("itemListElement") or []:
                if isinstance(el, dict):
                    name = el.get("name") or (el.get("item") or {}).get("name")
                    if name:
                        names.append(str(name))
            if names:
                out["breadcrumb"] = " > ".join(names)
    return out


def _longest_block(text: str) -> str:
    """ページ全体のテキストから、一番長い文章のかたまりを取る（本文の予想）。"""
    blocks, current = [], []
    for line in text.split("\n"):
        if len(line.strip()) >= 15:
            current.append(line.strip())
        else:
            if current:
                blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return max(blocks, key=len) if blocks else ""


def _clean_title(title: str) -> str:
    title = re.sub(r"\s*[|｜]\s*ココナラ.*$", "", title or "")
    return title.strip()


def parse_request(raw: dict, today: date | None = None) -> dict:
    """ブラウザで集めた生データ（search.fetch_request の戻り値）を、案件データにまとめる。"""
    today = today or date.today()
    text = raw.get("body_text", "")
    ld = _from_json_ld(raw.get("ld_json", []))

    title = ld.get("title") or raw.get("h1") or raw.get("og_title") or _clean_title(raw.get("title", ""))
    title = _clean_title(title)

    description = ld.get("description", "")
    if len(description) < 30:
        pre = [t for t in raw.get("pre_texts", []) if len(t) >= 30]
        description = max(pre, key=len) if pre else ""
    if len(description) < 30:
        og = raw.get("og_description", "")
        block = _longest_block(text)
        description = block if len(block) > len(og) else og

    breadcrumb = ld.get("breadcrumb") or " ".join(raw.get("breadcrumbs", []))

    budget = parse_budget(text)
    posted = parse_label_date(text, r"(掲載日|公開日|投稿日)")
    if not posted and ld.get("posted"):
        posted = _first_date(ld["posted"].replace("-", "/"))
    delivery = parse_label_date(text, r"(納品希望日|納期|希望納期)")
    days_left = parse_days_left(text, today)
    if days_left is None and ld.get("valid_through"):
        d = _first_date(ld["valid_through"].replace("-", "/"))
        days_left = (d - today).days if d else None

    return {
        "id": raw["id"],
        "url": raw["url"],
        "title": title,
        "breadcrumb": breadcrumb.strip(),
        "description": description.strip(),
        "budget": budget,
        "proposals": parse_proposals(text),
        "days_left": days_left,
        "posted": posted.isoformat() if posted else None,
        "delivery_date": delivery.isoformat() if delivery else None,
        "closed": is_closed(text),
        "page_text": text[:12000],
        "fetched_at": raw.get("fetched_at") or datetime.now().isoformat(timespec="seconds"),
    }
