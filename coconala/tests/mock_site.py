"""テスト用の小さな「ココナラ風」サイト。

本物のココナラの画面とは違います。ツールが、見出しの言葉やリンクの形を手がかりに
読み取れるかを確かめるためのものです。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HEADER = """<header><nav>仕事を探す 翻訳・語学 マーケティング 広報・PR 予算から探す
<a href="/requests/add">募集を作成</a> <a href="/mypage/requests/999">自分の募集</a>
<a href="/services/123">サービス</a></nav></header>"""


def page(title: str, body: str, head: str = "") -> str:
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>{title} | ココナラ</title><meta property="og:title" content="{title}">{head}</head>
<body>{HEADER}<main>{body}</main></body></html>"""


def request_page(rid: str, title: str, budget: str, proposals: str, deadline: str, desc: str,
                 extra_head: str = "", show_desc: bool = True) -> str:
    desc_html = f'<div style="white-space: pre-wrap">{desc}</div>' if show_desc else ""
    return page(title, f"""
<nav class="c-breadcrumb">ホーム &gt; 仕事を探す &gt; ビジネス代行 &gt; 市場調査・データ収集</nav>
<h1>{title}</h1>
<span>募集中</span>
<dl>
  <dt>予算</dt><dd>{budget}</dd>
  <dt>提案数</dt><dd>{proposals}</dd>
  <dt>募集期限</dt><dd>{deadline}</dd>
  <dt>納品希望日</dt><dd>2026年10月30日</dd>
</dl>
<h2>依頼内容</h2>
{desc_html}
<a href="/requests/{rid}/proposals/new" class="btn">提案する</a>
""", extra_head)


DESC_NY = """ニューヨークで日本食レストランの出店を考えています。
マンハッタンの日本食レストランの価格帯、客層、人気メニューを調べて、レポートにまとめてください。
現地で数店舗を実際に見ていただけると助かります。
納品はWordかPowerPointで、10ページ程度を想定しています。
修正は1回程度を想定しています。"""

DESC_UNPAID = """新しいアプリのアンケートに答えてくれる方を探しています。
今回はテストのため無償でお願いします。うまくいけば次回から有償の仕事をお願いするかもしれません。
アメリカの方の意見も知りたいです。よろしくお願いします。"""

DESC_TRANSLATION = "英語の会社案内（約3,000文字）を日本語に翻訳してください。用途はウェブサイトへの掲載です。読みやすい自然な日本語を希望します。"

DESC_LOGO = """カフェのロゴデザインを作ってくれる方を募集します。
イメージに合うまで何度でも修正をお願いすることがあります。
Illustratorのデータで納品してください。色は緑系を考えています。"""

JOBPOSTING = json.dumps({
    "@context": "https://schema.org", "@type": "JobPosting",
    "title": "英語の会社案内を日本語に翻訳",
    "description": DESC_TRANSLATION, "datePosted": "2026-10-12",
}, ensure_ascii=False)

ROUTES = {
    "/requests/1001": request_page("1001", "NYの日本食レストラン市場調査", "10,000円 〜 30,000円", "2", "あと5日", DESC_NY),
    "/requests/1002": request_page("1002", "アプリのアンケート回答（アメリカ在住の方）", "見積り希望", "8", "あと3日", DESC_UNPAID),
    "/requests/1003": request_page(
        "1003", "英語の会社案内を日本語に翻訳", "5千円〜1万円", "12", "あと2日", "",
        extra_head=f'<script type="application/ld+json">{JOBPOSTING}</script>', show_desc=False),
    "/requests/1004": request_page("1004", "カフェのロゴデザイン", "20,000円 〜 50,000円", "30", "あと7日", DESC_LOGO),
    "/requests/1001/proposals/new": page("提案を作成", """
<h1>提案を作成</h1>
<form method="post" action="/requests/1001/proposals">
  <label for="content">提案内容</label>
  <textarea id="content" name="content" rows="12" style="width:600px"></textarea>
  <div><label for="price">提案金額（税込）</label><input id="price" name="price" type="number"></div>
  <div><label for="delivery">納期</label><input id="delivery" name="delivery" type="date"></div>
  <input type="hidden" name="token" value="x">
  <button type="submit">提案を送信する</button>
</form>"""),
    "/login": page("ログイン", "<h1>ログイン</h1><input type='email'><input type='password'>"),
}

LISTING = page("仕事を探す", """
<h1>仕事を探す</h1>
<ul>
  <li><a href="/requests/1001">NYの日本食レストラン市場調査</a></li>
  <li><a href="https://coconala.com/requests/1002?ref=list">アプリのアンケート回答</a></li>
  <li><a href="/requests/1003/">英語の会社案内を日本語に翻訳</a></li>
  <li><a href="/requests/1004#top">カフェのロゴデザイン</a></li>
  <li><a href="/requests/1001">（同じ案件へのリンク）</a></li>
</ul>""")


class MockSite:
    def __init__(self):
        self.posts: list[str] = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status: int, body: str):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split("?")[0].split("#")[0]
                if path == "/requests":
                    return self._send(200, LISTING)
                if path in ROUTES:
                    return self._send(200, ROUTES[path])
                return self._send(404, page("not found", "<h1>404</h1>"))

            def do_POST(self):
                site.posts.append(self.path)
                return self._send(200, page("送信しました", "<h1>送信しました</h1>"))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
