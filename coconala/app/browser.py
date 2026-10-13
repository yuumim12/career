"""ブラウザ（Playwright）を開く。ログイン状態は profile_dir に保存される。"""
from __future__ import annotations

import os
import random
import time
from contextlib import contextmanager

from .config import resolve


@contextmanager
def open_browser(cfg: dict, headless: bool):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Playwright が入っていません。README の「準備」を見て、\n"
            "  pip install -r requirements.txt\n"
            "  playwright install chromium\n"
            "を実行してください。"
        )

    bcfg = cfg.get("browser", {})
    profile_dir = resolve(cfg, bcfg.get("profile_dir", ".browser-profile"))
    profile_dir.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "locale": "ja-JP",
        "viewport": {"width": 1280, "height": 900},
    }
    exe = os.environ.get("COCONALA_BROWSER_PATH") or bcfg.get("executable_path")
    if exe:
        kwargs["executable_path"] = exe
    elif bcfg.get("channel"):
        kwargs["channel"] = bcfg["channel"]

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(**kwargs)
        except Exception:
            if "channel" not in kwargs:
                raise
            print("Google Chrome が見つからないため、Playwright の Chromium を使います。")
            kwargs.pop("channel")
            ctx = p.chromium.launch_persistent_context(**kwargs)
        try:
            yield ctx
        finally:
            ctx.close()


def get_page(ctx):
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def polite_wait(cfg: dict) -> None:
    """サイトに負担をかけないよう、ページを開く間に少し待つ。"""
    lo, hi = cfg.get("search", {}).get("wait_seconds", [4, 8])
    if hi > 0:
        time.sleep(random.uniform(lo, hi))


def goto(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass  # 広告などで通信が止まらないページもあるので、待ちすぎない
