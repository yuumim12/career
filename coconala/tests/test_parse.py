from datetime import date

from app.parse import is_closed, parse_budget, parse_days_left, parse_proposals, parse_request


def test_budget_range():
    b = parse_budget("予算\n10,000円 〜 30,000円\n提案数\n3")
    assert (b["min"], b["max"], b["type"]) == (10000, 30000, "fixed")
    assert b["label"] == "10,000円 〜 30,000円"


def test_budget_japanese_units():
    b = parse_budget("予算：5千円〜1.5万円")
    assert (b["min"], b["max"]) == (5000, 15000)


def test_budget_only_upper_or_lower():
    assert parse_budget("予算\n〜5,000円")["max"] == 5000
    assert parse_budget("予算\n〜5,000円")["min"] is None
    b = parse_budget("予算\n30,000円〜")
    assert (b["min"], b["max"]) == (30000, None)


def test_budget_quote_and_hourly():
    assert parse_budget("予算\n見積り希望")["type"] == "quote"
    assert parse_budget("予算\n見積もりを希望")["type"] == "quote"
    b = parse_budget("予算\n時給 1,500円 〜 2,000円")
    assert (b["type"], b["min"], b["max"]) == ("hourly", 1500, 2000)


def test_budget_skips_label_without_amount():
    # 最初の「予算」は検索用のメニュー。2つ目が本当の予算
    b = parse_budget("予算から探す\n指定なし\n...\n予算\n20,000円")
    assert (b["min"], b["max"]) == (20000, 20000)


def test_budget_does_not_take_plain_numbers():
    assert parse_budget("予算\n提案数 5")["type"] == "unknown"


def test_proposals():
    assert parse_proposals("提案数\n12") == 12
    assert parse_proposals("提案 3件") == 3
    assert parse_proposals("5人が応募しています") == 5
    assert parse_proposals("応募\n2026年10月1日") is None


def test_days_left():
    today = date(2026, 10, 13)
    assert parse_days_left("募集期限\nあと5日", today) == 5
    assert parse_days_left("締切 2026年10月20日", today) == 7
    assert parse_days_left("本日締切", today) == 0
    assert parse_days_left("あと3時間で締め切り\n募集期限\nあと12時間", today) == 0


def test_closed():
    assert is_closed("タイトル\n募集終了\n予算")
    assert is_closed("この募集は終了しました")
    assert not is_closed("募集中\n募集終了した仕事を見る")


def test_parse_request_prefers_json_ld_and_pre_text():
    raw = {
        "id": "1", "url": "https://coconala.com/requests/1",
        "h1": "見出し", "title": "タイトル | ココナラ",
        "body_text": "予算\n5,000円\n提案数\n1\n募集期限\nあと2日\n納品希望日\n2026年10月30日",
        "pre_texts": ["依頼者が書いた本文です。" * 5],
        "breadcrumbs": ["ホーム > 翻訳"],
        "ld_json": ['{"@type": "BreadcrumbList", "itemListElement": [{"name": "ホーム"}, {"name": "翻訳・語学"}]}'],
        "og_description": "",
    }
    job = parse_request(raw, today=date(2026, 10, 13))
    assert job["title"] == "見出し"
    assert job["description"].startswith("依頼者が書いた本文です。")
    assert job["breadcrumb"] == "ホーム > 翻訳・語学"
    assert job["budget"]["max"] == 5000
    assert job["proposals"] == 1
    assert job["days_left"] == 2
    assert job["delivery_date"] == "2026-10-30"
    assert job["closed"] is False


def test_budget_prefers_field_over_sentence():
    # 本文の「予算は相談」より、見出しのすぐ後ろの金額を使う
    text = "依頼内容\n予算は相談させてください。\n...\n予算\n10,000円 〜 20,000円"
    b = parse_budget(text)
    assert (b["min"], b["max"]) == (10000, 20000)
    # 金額のない文だけなら、見積り希望とみなす
    assert parse_budget("予算は相談で決めたいです")["type"] == "quote"


def test_budget_labels():
    assert parse_budget("予算\n30,000円〜")["label"] == "30,000円〜"
    assert parse_budget("予算\n5,000円\n提案数\n2,000円")["label"] == "5,000円"
