#!/usr/bin/env python3
"""ココナラ案件ツール

  python coconala.py login           初回だけ。ブラウザでココナラにログインする
  python coconala.py run             ①〜④ 新着案件を探して、評価・提案文を作る
  python coconala.py apply 1         ⑤⑥ 提案フォームを開いて入力する（送信は自分で）
  python coconala.py list            前回の結果をもう一度表示する
  python coconala.py debug URL       ページの読み取りを確認する（うまく動かないとき）
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
import webbrowser
from datetime import datetime

from app.ai import AIReviewer, ai_available
from app.apply import prepare_application
from app.browser import get_page, goto, open_browser, polite_wait
from app.config import ROOT, load_config, load_dotenv, resolve
from app.parse import parse_request
from app.report import write_csv, write_html
from app.score import apply_ai_review, evaluate, sort_jobs
from app.search import COLLECT_JS, collect_request_ids, extract_request_ids, fetch_request
from app.state import Store
from app.template import make_proposal


def process(jobs: list[dict], cfg: dict, use_ai: bool) -> list[dict]:
    """②③ 評価と並べ替え、④ 提案文の作成。"""
    for job in jobs:
        evaluate(job, cfg)
    jobs = sort_jobs(jobs)

    if use_ai:
        profile = (ROOT / "profile.md").read_text(encoding="utf-8")
        reviewer = AIReviewer(cfg, profile)
        limit = int(cfg.get("ai", {}).get("max_reviews", 8))
        targets = [j for j in jobs if not j["eval"]["excluded"]][:limit]
        if targets:
            print(f"④ AIが上位{len(targets)}件を読んで、提案文を書いています…")
        for n, job in enumerate(targets, 1):
            print(f"   [{n}/{len(targets)}] {job['title'][:40]}")
            review = reviewer.review(job)
            if review:
                apply_ai_review(job, review, cfg)
                job["proposal"] = review["proposal"]
        jobs = sort_jobs(jobs)

    for job in jobs:
        if not job.get("proposal") and not job["eval"]["excluded"]:
            job["proposal"] = make_proposal(job, cfg)
    return jobs


def _pad(text: str, width: int) -> str:
    """全角文字を2文字分として、表の幅をそろえる。"""
    out, used = "", 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if used + w > width:
            break
        out, used = out + ch, used + w
    return out + " " * (width - used)


def print_table(jobs: list[dict], limit: int = 10) -> None:
    active = [j for j in jobs if not j["eval"]["excluded"]]
    if not active:
        print("\n今回は候補がありませんでした。")
        return
    print("\n番号 ランク 点数 " + _pad("予算", 22) + _pad("提案数", 7) + "タイトル")
    for i, j in enumerate(active[:limit], 1):
        ev = j["eval"]
        props = "?" if j.get("proposals") is None else str(j["proposals"])
        print(f"{i:>3}.  {ev['rank']}    {ev['total']:>3}  " + _pad(j["budget"]["label"], 22)
              + _pad(props, 7) + _pad(j["title"], 50).rstrip())


def ask_and_apply(jobs: list[dict], cfg: dict, store: Store) -> None:
    active = [j for j in jobs if not j["eval"]["excluded"]]
    while active:
        try:
            ans = input("\n応募の準備をする案件の番号を入れてください（Enterで終了）: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not ans:
            return
        if not ans.isdigit() or not (1 <= int(ans) <= len(active)):
            print("番号をもう一度入れてください。")
            continue
        job = active[int(ans) - 1]
        prepare_application(cfg, job, job["proposal"], store)


def cmd_run(cfg: dict, args) -> None:
    store = Store(resolve(cfg, cfg.get("data_dir", "data")))
    jobs: list[dict] = []
    with open_browser(cfg, headless=not args.show) as ctx:
        page = get_page(ctx)
        print("① 募集一覧から案件を探しています…")
        ids = collect_request_ids(page, cfg)
        new_ids = [i for i in ids if (args.all or i not in store.seen) and i not in store.applied]
        limit = int(cfg.get("search", {}).get("max_new_requests", 30))
        targets = new_ids[:limit]
        print(f"   見つかった案件 {len(ids)}件 ／ 新しい案件 {len(new_ids)}件 ／ 今回読む {len(targets)}件")
        for n, rid in enumerate(targets, 1):
            polite_wait(cfg)
            try:
                raw = fetch_request(page, rid, cfg)
            except Exception as e:
                print(f"   [{n}/{len(targets)}] {rid}: 読めませんでした（{type(e).__name__}）")
                continue
            job = parse_request(raw)
            jobs.append(job)
            store.mark_seen(rid)
            print(f"   [{n}/{len(targets)}] {job['title'][:40]}")
    store.save()

    print("②③ 評価して、順番を付けています…")
    use_ai = not args.no_ai and ai_available(cfg)
    if not use_ai:
        print("   （AIは使わず、テンプレートで提案文を作ります）")
    jobs = process(jobs, cfg, use_ai)
    for job in jobs:
        store.save_job(job)
    active = [j for j in jobs if not j["eval"]["excluded"]]
    store.save_last_run([j["id"] for j in active])

    out = resolve(cfg, cfg.get("output_dir", "output"))
    run_dir = out / datetime.now().strftime("%Y-%m-%d_%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)
    write_html(jobs, run_dir / "report.html", {"fetched": len(jobs)})
    write_csv(jobs, run_dir / "jobs.csv")
    shutil.copy(run_dir / "report.html", out / "latest.html")
    print(f"\nレポート: {run_dir / 'report.html'}")

    print_table(jobs)
    if not args.no_prompt:
        webbrowser.open((run_dir / "report.html").as_uri())
        ask_and_apply(jobs, cfg, store)


def cmd_list(cfg: dict, args) -> None:
    store = Store(resolve(cfg, cfg.get("data_dir", "data")))
    jobs = [j for j in (store.load_job(i) for i in store.load_last_run()) if j]
    jobs = [j for j in jobs if j["id"] not in store.applied]
    print_table(jobs, limit=50)
    latest = resolve(cfg, cfg.get("output_dir", "output")) / "latest.html"
    if latest.exists():
        print(f"\nレポート: {latest}")
    if not args.no_prompt:
        ask_and_apply(jobs, cfg, store)


def cmd_apply(cfg: dict, args) -> None:
    store = Store(resolve(cfg, cfg.get("data_dir", "data")))
    key = args.target
    m = re.search(r"/requests/(\d+)", key)
    if m:
        key = m.group(1)
    last = store.load_last_run()
    if key.isdigit() and len(key) <= 3 and 1 <= int(key) <= len(last):
        key = last[int(key) - 1]  # 「apply 1」= 前回のリストの1番

    job = store.load_job(key)
    if not job:
        print("この案件はまだ読んでいないので、先に読みます…")
        with open_browser(cfg, headless=True) as ctx:
            job = parse_request(fetch_request(get_page(ctx), key, cfg))
        job = process([job], cfg, use_ai=not args.no_ai and ai_available(cfg))[0]
        store.save_job(job)
        if job["eval"]["excluded"]:
            print("注意: この案件は「" + "／".join(job["eval"]["excluded"]) + "」に当てはまります。")
            if not job.get("proposal"):
                job["proposal"] = make_proposal(job, cfg)

    print(f"\n{job['title']}\n{job['url']}")
    print(f"提案金額 {job['eval']['price']:,}円 ／ 納期の目安 {job['eval']['days']}日")
    print("ブラウザで提案フォームを開いて入力します。送信は、ご自身で確認してから押してください。")
    prepare_application(cfg, job, job["proposal"], store)


def cmd_login(cfg: dict, args) -> None:
    base = cfg.get("search", {}).get("base_url", "https://coconala.com").rstrip("/")
    with open_browser(cfg, headless=False) as ctx:
        page = get_page(ctx)
        goto(page, f"{base}/login")
        input("ブラウザでココナラにログインしてください。終わったら、ここで Enter を押してください。")
    print("ログイン状態を保存しました。次回からはログインなしで使えます。")


def cmd_debug(cfg: dict, args) -> None:
    out = resolve(cfg, cfg.get("output_dir", "output")) / "debug"
    out.mkdir(parents=True, exist_ok=True)
    with open_browser(cfg, headless=not args.show) as ctx:
        page = get_page(ctx)
        goto(page, args.url)
        page.screenshot(path=str(out / "page.png"), full_page=True)
        (out / "page.html").write_text(page.content(), encoding="utf-8")
        m = re.search(r"/requests/(\d+)/?$", args.url.split("?")[0])
        if m:
            raw = page.evaluate(COLLECT_JS)
            raw.update({"id": m.group(1), "url": args.url})
            job = parse_request(raw)
            (out / "raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            (out / "parsed.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            for k in ("title", "breadcrumb", "budget", "proposals", "days_left", "delivery_date", "closed"):
                print(f"{k}: {job[k]}")
            print(f"description: {job['description'][:200]}")
        else:
            hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
            ids = extract_request_ids(hrefs, page.url)
            print(f"このページで見つかった案件: {len(ids)}件 {ids[:10]}")
    print(f"\n保存しました: {out}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ココナラ案件ツール")
    parser.add_argument("--config", help="設定ファイル（ふだんは不要）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="新着案件を探して、評価・提案文を作る")
    p.add_argument("--all", action="store_true", help="前に見た案件ももう一度読む")
    p.add_argument("--no-ai", action="store_true", help="AIを使わない")
    p.add_argument("--no-prompt", action="store_true", help="最後に番号を聞かない（自動実行用）")
    p.add_argument("--show", action="store_true", help="ブラウザの画面を表示する")

    p = sub.add_parser("apply", help="提案フォームを開いて入力する（送信は自分で）")
    p.add_argument("target", help="前回のリストの番号、案件ID、または案件のURL")
    p.add_argument("--no-ai", action="store_true", help="AIを使わない")

    p = sub.add_parser("list", help="前回の結果をもう一度表示する")
    p.add_argument("--no-prompt", action="store_true")

    sub.add_parser("login", help="ブラウザでココナラにログインする（初回だけ）")

    p = sub.add_parser("debug", help="ページの読み取りを確認する")
    p.add_argument("url")
    p.add_argument("--show", action="store_true")

    args = parser.parse_args(argv)
    load_dotenv()
    cfg = load_config(args.config)
    {"run": cmd_run, "apply": cmd_apply, "list": cmd_list, "login": cmd_login, "debug": cmd_debug}[args.cmd](cfg, args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n中止しました。")
