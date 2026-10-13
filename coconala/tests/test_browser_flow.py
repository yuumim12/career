"""ブラウザを使った通しのテスト（テスト用の模擬サイトに対して実行）。"""
import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("playwright")

import coconala  # noqa: E402
from app.apply import prepare_application  # noqa: E402
from app.config import load_config  # noqa: E402
from app.state import Store  # noqa: E402
from tests.mock_site import MockSite  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def site():
    with MockSite() as s:
        yield s


@pytest.fixture()
def cfg_path(tmp_path, site):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["search"].update({"base_url": site.url, "keywords": ["テスト"], "wait_seconds": [0, 0]})
    cfg["browser"]["channel"] = ""
    cfg["ai"]["enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def _launch_ok():
    from playwright.sync_api import sync_playwright
    import os
    try:
        with sync_playwright() as p:
            kw = {"executable_path": os.environ["COCONALA_BROWSER_PATH"]} if os.environ.get("COCONALA_BROWSER_PATH") else {}
            p.chromium.launch(**kw).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _launch_ok(), reason="ブラウザが起動できない環境")


def test_run_then_apply(cfg_path, site, tmp_path):
    coconala.main(["--config", str(cfg_path), "run", "--no-prompt"])

    cfg = load_config(cfg_path)
    store = Store(tmp_path / "data")
    assert set(store.seen) == {"1001", "1002", "1003", "1004"}

    order = store.load_last_run()
    assert order[0] == "1001"           # NYの市場調査が一番上
    assert "1003" in order              # 翻訳も候補
    assert "1002" not in order          # 無償なので外す
    assert "1004" not in order          # ロゴデザイン（スキル外・修正無制限）は外す

    ny = store.load_job("1001")
    assert ny["budget"]["max"] == 30000 and ny["proposals"] == 2 and ny["days_left"] == 5
    assert "マンハッタン" in ny["description"]
    assert ny["proposal"].startswith("はじめまして")
    tr = store.load_job("1003")
    assert tr["description"].startswith("英語の会社案内")  # 構造化データから本文を取れた
    unpaid = store.load_job("1002")
    assert any(r.startswith("無報酬") for r in unpaid["eval"]["excluded"])

    report = (tmp_path / "output" / "latest.html").read_text(encoding="utf-8")
    assert "NYの日本食レストラン市場調査" in report and "外した案件" in report
    csv_files = list((tmp_path / "output").glob("*/jobs.csv"))
    assert csv_files

    # 2回目は新しい案件がないので、何も読まない
    coconala.main(["--config", str(cfg_path), "run", "--no-prompt"])
    assert store.load_last_run() == order or Store(tmp_path / "data").load_last_run() == []

    # ⑤⑥ フォームに入力するが、送信はしない
    result = prepare_application(cfg, ny, ny["proposal"], headless=True, wait_for_user=False)
    assert result["text"] and result["price"]
    assert site.posts == []


def test_debug_command(cfg_path, site, tmp_path, capsys):
    coconala.main(["--config", str(cfg_path), "debug", f"{site.url}/requests/1001"])
    parsed = json.loads((tmp_path / "output" / "debug" / "parsed.json").read_text(encoding="utf-8"))
    assert parsed["title"] == "NYの日本食レストラン市場調査"
    coconala.main(["--config", str(cfg_path), "debug", f"{site.url}/requests?keyword=x"])
    assert "4件" in capsys.readouterr().out
