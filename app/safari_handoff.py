"""Open a WeChat article in Safari and hand it off to WeChat Desktop.

The article page's blue account name (#js_name, under the title) must be
clicked; that always shows 「即将前往微信打开此文章」.  Then click 「前往」.
Credential capture still happens in Schinza's MITM — this module only drives
Safari / the confirmation dialog.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Callable

RunFn = Callable[..., subprocess.CompletedProcess[str]]


CLICK_NAME_JS = (
    "(function () {"
    " var el = document.getElementById('js_name');"
    " if (el) { el.click(); return 'clicked-js_name'; }"
    " var meta = document.querySelector('#meta_content a, .rich_media_meta_list a, a.wx_tap_link');"
    " if (meta) { meta.click(); return 'clicked-meta'; }"
    " var nodes = document.querySelectorAll('a, span, strong');"
    " for (var i = 0; i < nodes.length; i++) {"
    "  var n = nodes[i];"
    "  if (n.id === 'js_name' || (n.className && String(n.className).indexOf('profile') >= 0)) {"
    "   n.click(); return 'clicked-profile';"
    "  }"
    " }"
    " return 'name-not-found';"
    "})();"
)

CLICK_GO_JS = (
    "(function () {"
    " var primary = document.querySelector("
    "  '.weui-dialog__btn_primary, a.weui-dialog__btn_primary, .weui-dialog__btn.weui-dialog__btn_primary'"
    " );"
    " if (primary) { primary.click(); return 'clicked-primary'; }"
    " var nodes = document.querySelectorAll('a, button, span, div, input');"
    " for (var i = 0; i < nodes.length; i++) {"
    "  var t = (nodes[i].innerText || nodes[i].textContent || '').replace(/\\s+/g, ' ').trim();"
    "  if (t === '前往') { nodes[i].click(); return 'clicked-go'; }"
    " }"
    " return 'go-not-found';"
    "})();"
)

READY_JS = "(function () { return document.readyState + '|' + (location.href || ''); })();"


def _as_literal(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _run_osascript(source: str, *, timeout: float = 40.0, run: RunFn | None = None) -> str:
    runner = run or subprocess.run
    proc = runner(
        ["osascript", "-"],
        input=source,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(err or out or f"osascript exited {proc.returncode}")
    return out


def safari_do_javascript(js: str, *, timeout: float = 40.0, run: RunFn | None = None) -> str:
    source = (
        "tell application \"Safari\"\n"
        "  if (count of documents) is 0 then return \"no-document\"\n"
        f"  return do JavaScript {_as_literal(js)} in front document\n"
        "end tell\n"
    )
    return _run_osascript(source, timeout=timeout, run=run)


def open_in_safari(url: str, *, run: RunFn | None = None) -> None:
    runner = run or subprocess.run
    proc = runner(
        ["open", "-a", "Safari", url],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or "无法用 Safari 打开文章")


def wait_safari_article(*, timeout_s: float = 35.0, run: RunFn | None = None) -> str:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            last = safari_do_javascript(READY_JS, run=run)
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(0.8)
            continue
        state, _, href = last.partition("|")
        if "complete" in state and "mp.weixin.qq.com" in href:
            return last
        time.sleep(0.6)
    raise RuntimeError(f"Safari 文章页未就绪：{last}")


def click_system_go_button(*, run: RunFn | None = None) -> str:
    source = """
tell application "System Events"
  set procs to {"Safari", "微信", "WeChat", "Weixin"}
  repeat with procName in procs
    if exists process procName then
      tell process procName
        set frontmost to true
        try
          click (first button whose name is "前往")
          return "ax-clicked:" & procName
        end try
        try
          click button "前往" of sheet 1 of window 1
          return "ax-sheet:" & procName
        end try
        try
          click button "前往" of window 1
          return "ax-window:" & procName
        end try
      end tell
    end if
  end repeat
end tell
return "ax-miss"
"""
    try:
        return _run_osascript(source, timeout=15, run=run)
    except Exception as exc:  # noqa: BLE001
        return f"ax-error:{exc}"


def accessibility_hint() -> str:
    return (
        "请在「系统设置 → 隐私与安全性 → 辅助功能」中允许终端 / Python / Schinza，"
        "并在 Safari「开发」菜单勾选「允许来自 Apple 事件的 JavaScript」。"
        "Safari 设置 → 高级 → 显示开发者功能 后才会出现开发菜单。"
    )


def handoff_article_to_wechat(
    url: str,
    *,
    run: RunFn | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """Open url in Safari, click the blue account name, then 前往."""

    if sys.platform != "darwin":
        raise RuntimeError("Safari 交接到微信仅支持 macOS")
    open_in_safari(url, run=run)
    sleep(1.2)
    ready = wait_safari_article(run=run)
    sleep(1.5)
    name_hit = "name-not-found"
    for _ in range(6):
        name_hit = safari_do_javascript(CLICK_NAME_JS, run=run)
        if name_hit.startswith("clicked"):
            break
        sleep(0.8)
    if not name_hit.startswith("clicked"):
        raise RuntimeError(
            f"未能点击文章页蓝字公众号名称（{name_hit}）。{accessibility_hint()}"
        )
    sleep(1.0)
    go_js = safari_do_javascript(CLICK_GO_JS, run=run)
    ax = "skipped"
    if not go_js.startswith("clicked"):
        sleep(0.4)
        ax = click_system_go_button(run=run)
        if not str(ax).startswith("ax-clicked") and not str(ax).startswith("ax-sheet") and not str(ax).startswith("ax-window"):
            raise RuntimeError(
                f"已点击公众号名称，但没有点到「前往」（js={go_js}, ax={ax}）。"
                + accessibility_hint()
            )
    return {"ready": ready, "name": name_hit, "go_js": go_js, "go_ax": ax}
