"""⑤ 応募準備 と ⑥ 応募：提案フォームを開いて、提案文と金額を入力する。

送信ボタンは押しません。最後の確認と送信は、ご自身で行ってください。
（まちがった内容を送らないため、そして機械的な大量送信と見られないため）
"""
from __future__ import annotations

import re

from .browser import get_page, goto

PROPOSE_BUTTON = re.compile(r"提案する|提案を作成|提案を送る|この仕事に提案|見積り.{0,4}提案|応募する")
PRICE_HINT = re.compile(r"金額|価格|見積|料金|報酬|price|amount", re.I)

INPUTS_JS = r"""
() => [...document.querySelectorAll("input")].map((el, i) => {
  const r = el.getBoundingClientRect();
  const visible = r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
  let label = "";
  if (el.id) {
    const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (l) label += l.innerText;
  }
  const wrap = el.closest("label");
  if (wrap) label += " " + wrap.innerText;
  let p = el.parentElement;
  for (let k = 0; k < 4 && p; k++, p = p.parentElement) {
    const t = (p.innerText || "").trim();
    if (t && t.length < 80) { label += " " + t; break; }
  }
  return {
    i, type: el.type || "", name: el.name || "", id: el.id || "",
    placeholder: el.placeholder || "", aria: el.getAttribute("aria-label") || "",
    label, visible, disabled: el.disabled || el.readOnly,
  };
})
"""

BANNER_JS = r"""
(msg) => {
  const box = document.createElement("div");
  box.textContent = msg;
  box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:360px;" +
    "padding:12px 14px;background:#1f4e79;color:#fff;font:14px/1.6 sans-serif;border-radius:8px;" +
    "box-shadow:0 4px 16px rgba(0,0,0,.3);pointer-events:none;white-space:pre-line";
  document.body.appendChild(box);
}
"""


def _first_visible(locator):
    for i in range(min(locator.count(), 10)):
        item = locator.nth(i)
        try:
            if item.is_visible():
                return item
        except Exception:
            continue
    return None


def click_propose(page):
    """「提案する」ボタンを押す。新しいタブが開いたら、そのタブを返す。"""
    target = _first_visible(page.get_by_role("button", name=PROPOSE_BUTTON)) or _first_visible(
        page.get_by_role("link", name=PROPOSE_BUTTON)
    )
    if not target:
        return None
    ctx = page.context
    before = len(ctx.pages)
    target.click()
    page.wait_for_timeout(2500)
    if len(ctx.pages) > before:
        new_page = ctx.pages[-1]
        new_page.wait_for_load_state("domcontentloaded")
        return new_page
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    return page


def needs_login(page) -> bool:
    if re.search(r"login|signin|sign_in", page.url, re.I):
        return True
    return page.locator("input[type=password]").count() > 0


def fill_form(page, text: str, price: int) -> dict:
    result = {"text": False, "price": False}

    # 提案文：見えているテキストエリアの中で、一番大きいもの
    best, best_area = None, 0
    areas = page.locator("textarea")
    for i in range(areas.count()):
        ta = areas.nth(i)
        try:
            if not ta.is_visible() or not ta.is_editable():
                continue
            box = ta.bounding_box() or {"width": 0, "height": 0}
        except Exception:
            continue
        area = box["width"] * box["height"]
        if area > best_area:
            best, best_area = ta, area
    if best:
        best.fill(text)
        best.evaluate("el => el.style.outline = '3px solid #2e86de'")
        result["text"] = best.input_value() == text

    # 金額：「金額」「価格」などの見出しがついた入力欄
    for info in page.evaluate(INPUTS_JS):
        if not info["visible"] or info["disabled"]:
            continue
        if info["type"] not in ("", "text", "number", "tel"):
            continue
        hints = " ".join([info["name"], info["id"], info["placeholder"], info["aria"], info["label"]])
        if PRICE_HINT.search(hints):
            field = page.locator("input").nth(info["i"])
            field.fill(str(price))
            field.evaluate("el => el.style.outline = '3px solid #2e86de'")
            result["price"] = field.input_value().replace(",", "") == str(price)
            break
    return result


def prepare_application(cfg: dict, job: dict, proposal: str, store=None,
                        headless: bool = False, wait_for_user: bool = True, log=print) -> dict:
    from .browser import open_browser

    ev = job["eval"]
    result = {"form_found": False, "text": False, "price": False, "applied": False}
    with open_browser(cfg, headless=headless) as ctx:
        page = get_page(ctx)
        goto(page, job["url"])
        form_page = click_propose(page)
        if form_page and needs_login(form_page) and wait_for_user:
            input("\nブラウザでココナラにログインしてください。終わったら Enter を押してください。")
            goto(page, job["url"])
            form_page = click_propose(page)
        page = form_page or page

        filled = fill_form(page, proposal, ev["price"])
        if not filled["text"] and wait_for_user:
            log("\n提案フォームが自動で見つかりませんでした。")
            input("ブラウザで提案フォームを開いてから、Enter を押してください。")
            page = ctx.pages[-1]
            filled = fill_form(page, proposal, ev["price"])
        result.update(filled)
        result["form_found"] = filled["text"]

        if filled["text"]:
            page.evaluate(
                BANNER_JS,
                "自動で入力しました（青い枠）。\n内容を確認して、送信ボタンはご自身で押してください。\n"
                f"提案金額 {ev['price']:,}円 / 納期の目安 {ev['days']}日",
            )
        print_checklist(job, filled, log)

        if wait_for_user:
            try:
                answer = input("\n送信しましたか？ 送った → y / 送っていない → Enter : ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer in ("y", "yes", "はい"):
                result["applied"] = True
                if store:
                    store.mark_applied(job["id"])
                log("応募済みとして記録しました。")
    return result


def print_checklist(job: dict, filled: dict, log=print) -> None:
    ev = job["eval"]
    ok = lambda b: "入力ずみ" if b else "★手で入力してください"  # noqa: E731
    log("\n--- 送信する前の確認 ---")
    log(f"・提案文: {ok(filled['text'])}")
    log(f"・提案金額 {ev['price']:,}円: {ok(filled['price'])}")
    log(f"・納期（目安 {ev['days']}日）: 日付の欄があれば手で選んでください")
    log("・提案するサービスの選択や、添付ファイルの欄があれば確認してください")
    log("・連絡先やURLが入っていないか（ココナラの規約で禁止）")
    if ev.get("questions"):
        log("・依頼者に聞きたいこと: " + " / ".join(ev["questions"]))
