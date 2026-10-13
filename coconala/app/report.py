"""結果をHTML（ブラウザで見る用）とCSV（表計算ソフト用）で保存する。"""
from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path

CSS = """
:root { --bg:#f7f7f5; --card:#fff; --text:#222; --sub:#666; --line:#e2e2de; --accent:#1f4e79;
        --a:#1b7f4b; --b:#b07d12; --c:#888; --ex:#a33; --badge:#fff; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#17181a; --card:#222326; --text:#eee; --sub:#aaa; --line:#3a3b3f; --accent:#7fb2e5;
          --a:#5cc68f; --b:#e0b24f; --c:#999; --ex:#e07a7a; --badge:#111; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.7 -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif; }
main { max-width: 920px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.summary { color: var(--sub); margin-bottom: 24px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin-bottom:16px; }
.head { display:flex; gap:12px; align-items:flex-start; }
.rank { flex:none; width:44px; height:44px; border-radius:8px; color:var(--badge); display:flex; align-items:center;
        justify-content:center; font-weight:700; font-size:20px; }
.rank.A { background:var(--a); } .rank.B { background:var(--b); } .rank.C { background:var(--c); }
.title { font-size:17px; font-weight:600; }
.title a { color:var(--accent); text-decoration:none; }
.meta { color:var(--sub); font-size:13px; }
.facts { display:flex; flex-wrap:wrap; gap:6px 16px; margin:10px 0; font-size:14px; }
.facts b { font-weight:600; }
.bars { display:grid; grid-template-columns: repeat(4, 1fr); gap:8px; font-size:12px; color:var(--sub); margin:8px 0; }
.bar { height:6px; background:var(--line); border-radius:3px; overflow:hidden; }
.bar span { display:block; height:100%; background:var(--accent); }
ul { margin:6px 0; padding-left:20px; }
.ai { border-left:3px solid var(--accent); padding:4px 10px; margin:8px 0; font-size:14px; }
details { margin-top:8px; }
textarea { width:100%; min-height:260px; font:inherit; font-size:14px; padding:10px; border:1px solid var(--line);
           border-radius:6px; background:var(--bg); color:var(--text); }
button { margin-top:6px; padding:6px 12px; border:1px solid var(--line); border-radius:6px; background:var(--card);
         color:var(--text); cursor:pointer; font-size:13px; }
code { background:var(--bg); padding:2px 6px; border-radius:4px; font-size:13px; }
.excluded li { color:var(--sub); }
.excluded .why { color:var(--ex); }
@media (max-width: 600px) { .bars { grid-template-columns: repeat(2, 1fr); } }
"""

SCRIPT = """
function copyText(id, btn) {
  const t = document.getElementById(id);
  navigator.clipboard.writeText(t.value).then(() => { btn.textContent = "コピーしました"; });
}
"""

PART_NAMES = {"fit": "スキル", "pay": "時給", "win": "受注しやすさ", "clarity": "わかりやすさ"}


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _facts(job: dict) -> str:
    ev = job["eval"]
    items = [
        ("予算", job["budget"]["label"]),
        ("提案数", f"{job['proposals']}件" if job.get("proposals") is not None else "不明"),
        ("締め切り", f"あと{job['days_left']}日" if job.get("days_left") is not None else "不明"),
        ("作業時間の目安", f"{ev['hours']}時間"),
        ("手取り時給", f"{ev['hourly_net']:,}円" if ev.get("hourly_net") else "－"),
        ("提案金額", f"{ev['price']:,}円"),
        ("納期", f"{ev['days']}日"),
    ]
    return "".join(f"<span>{_e(k)}: <b>{_e(v)}</b></span>" for k, v in items)


def _bars(ev: dict) -> str:
    out = []
    for key, name in PART_NAMES.items():
        v = ev["parts"][key]
        out.append(f'<div>{name} {v}<div class="bar"><span style="width:{v}%"></span></div></div>')
    return "".join(out)


def _card(n: int, job: dict) -> str:
    ev = job["eval"]
    reasons = "".join(f"<li>{_e(r)}</li>" for r in ev["reasons"])
    ai = ""
    if ev.get("source") == "ai":
        flags = "、".join(ev.get("ai_red_flags") or []) or "なし"
        ai = (f'<div class="ai">AIの判断: <b>{_e(ev["ai_recommend"])}</b>　{_e(ev["ai_reason"])}<br>'
              f'修正が増えるリスク: {_e(ev.get("revision_risk"))} ／ 気になる点: {_e(flags)}</div>')
    tid = f"p{job['id']}"
    return f"""
<div class="card">
  <div class="head">
    <div class="rank {ev['rank']}">{ev['rank']}</div>
    <div>
      <div class="title">{n}. <a href="{_e(job['url'])}" target="_blank" rel="noopener">{_e(job['title'])}</a></div>
      <div class="meta">合計 {ev['total']}点 ／ {_e(ev['category'] or '分野なし')} ／ {_e(job.get('breadcrumb') or '')}</div>
    </div>
  </div>
  <div class="facts">{_facts(job)}</div>
  <div class="bars">{_bars(ev)}</div>
  <ul>{reasons}</ul>
  {ai}
  <details>
    <summary>依頼の本文を見る</summary>
    <p style="white-space:pre-wrap">{_e(job['description'][:3000])}</p>
  </details>
  <details open>
    <summary>提案文（{'AI' if ev.get('source') == 'ai' else 'テンプレート'}）</summary>
    <textarea id="{tid}">{_e(job.get('proposal', ''))}</textarea>
    <button onclick="copyText('{tid}', this)">コピー</button>
    <div class="meta">応募の準備: ターミナルで <code>python coconala.py apply {_e(job['id'])}</code></div>
  </details>
</div>"""


def write_html(jobs: list[dict], path: Path, stats: dict) -> None:
    active = [j for j in jobs if not j["eval"]["excluded"]]
    excluded = [j for j in jobs if j["eval"]["excluded"]]
    cards = "".join(_card(i, j) for i, j in enumerate(active, 1))
    ex_items = "".join(
        f'<li><a href="{_e(j["url"])}" target="_blank" rel="noopener">{_e(j["title"])}</a> '
        f'<span class="why">— {_e("／".join(j["eval"]["excluded"]))}</span></li>'
        for j in excluded
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ココナラ案件リスト</title><style>{CSS}</style></head>
<body><main>
<h1>ココナラ案件リスト</h1>
<div class="summary">{now} ／ 新しく読んだ案件 {stats.get('fetched', 0)}件 ／
候補 {len(active)}件 ／ 外した案件 {len(excluded)}件</div>
{cards or '<p>今回は候補がありませんでした。</p>'}
<div class="card excluded"><b>外した案件（{len(excluded)}件）</b><ul>{ex_items or '<li>なし</li>'}</ul></div>
</main><script>{SCRIPT}</script></body></html>"""
    path.write_text(page, encoding="utf-8")


def write_csv(jobs: list[dict], path: Path) -> None:
    cols = ["順位", "ランク", "合計点", "タイトル", "URL", "予算", "提案数", "締め切りまで(日)",
            "作業時間", "手取り時給", "提案金額", "納期(日)", "スキル", "時給点", "受注しやすさ",
            "わかりやすさ", "AI判断", "外した理由"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # Excelで文字化けしないようBOM付き
        w = csv.writer(f)
        w.writerow(cols)
        for i, j in enumerate(jobs, 1):
            ev = j["eval"]
            w.writerow([
                i, ev["rank"], ev["total"], j["title"], j["url"], j["budget"]["label"], j.get("proposals"),
                j.get("days_left"), ev["hours"], ev.get("hourly_net"), ev["price"], ev["days"],
                ev["parts"]["fit"], ev["parts"]["pay"], ev["parts"]["win"], ev["parts"]["clarity"],
                ev.get("ai_recommend", ""), "／".join(ev["excluded"]),
            ])
