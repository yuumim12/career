"""① 案件検索：募集一覧から案件のIDを集め、詳しいページを読む。"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote, urljoin, urlparse, urlencode, parse_qsl, urlunparse

from .browser import goto, polite_wait

REQUEST_PATH = re.compile(r"^/requests/(\d+)/?$")

# 案件ページから、本文・タイトル・構造化データなどをまとめて取り出す
COLLECT_JS = r"""
() => {
  const meta = (p) => {
    const el = document.querySelector(`meta[property="${p}"], meta[name="${p}"]`);
    return el ? (el.getAttribute("content") || "") : "";
  };
  const h1 = document.querySelector("h1");
  // 依頼者が書いた本文は、改行をそのまま表示する設定（pre-wrap など）のことが多い
  const pre = [];
  for (const el of document.querySelectorAll("body *")) {
    const ws = getComputedStyle(el).whiteSpace;
    if (!["pre-wrap", "pre-line", "pre"].includes(ws)) continue;
    const parentWs = el.parentElement ? getComputedStyle(el.parentElement).whiteSpace : "";
    if (parentWs === ws) continue;
    const t = (el.innerText || "").trim();
    if (t.length >= 30) pre.push(t);
  }
  const crumbs = [...document.querySelectorAll(
    '[class*="readcrumb"], nav[aria-label*="readcrumb"], [itemtype*="BreadcrumbList"]'
  )].map(e => (e.innerText || "").trim()).filter(Boolean);
  const ld = [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent);
  return {
    h1: h1 ? h1.innerText.trim() : "",
    title: document.title || "",
    og_title: meta("og:title"),
    og_description: meta("og:description"),
    body_text: (document.querySelector("main") || document.body).innerText || "",
    pre_texts: pre,
    breadcrumbs: crumbs,
    ld_json: ld,
  };
}
"""


def build_search_urls(cfg: dict) -> list[str]:
    s = cfg.get("search", {})
    base = s.get("base_url", "https://coconala.com").rstrip("/")
    tmpl = s.get("url_template", "{base}/requests?keyword={keyword}")
    first_pages = [tmpl.format(base=base, keyword=quote(k)) for k in s.get("keywords", [])]
    first_pages += list(s.get("extra_urls") or [])
    urls = []
    for url in first_pages:
        urls.append(url)
        for n in range(2, int(s.get("pages_per_search", 1)) + 1):
            urls.append(_with_param(url, s.get("page_param", "page"), str(n)))
    return urls


def _with_param(url: str, key: str, value: str) -> str:
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != key]
    query.append((key, value))
    return urlunparse(parts._replace(query=urlencode(query)))


def extract_request_ids(hrefs: list[str], page_url: str) -> list[str]:
    ids = []
    for href in hrefs:
        if not href:
            continue
        path = urlparse(urljoin(page_url, href)).path
        m = REQUEST_PATH.match(path)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def collect_request_ids(page, cfg: dict, log=print) -> list[str]:
    ids: list[str] = []
    urls = build_search_urls(cfg)
    for i, url in enumerate(urls, 1):
        try:
            goto(page, url)
            hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
        except Exception as e:  # 1つのページで失敗しても、ほかは続ける
            log(f"  [{i}/{len(urls)}] 開けませんでした: {url} ({type(e).__name__})")
            continue
        found = extract_request_ids(hrefs, page.url)
        new = [x for x in found if x not in ids]
        ids.extend(new)
        log(f"  [{i}/{len(urls)}] {len(found)}件 {url}")
        if not found:
            log("    → 案件が見つかりません。ブラウザでこのURLを開いて確認してください（README「うまく動かないとき」）")
        if i < len(urls):
            polite_wait(cfg)
    return ids


def fetch_request(page, req_id: str, cfg: dict) -> dict:
    base = cfg.get("search", {}).get("base_url", "https://coconala.com").rstrip("/")
    url = f"{base}/requests/{req_id}"
    goto(page, url)
    data = page.evaluate(COLLECT_JS)
    data.update({"id": req_id, "url": url, "fetched_at": datetime.now().isoformat(timespec="seconds")})
    return data
