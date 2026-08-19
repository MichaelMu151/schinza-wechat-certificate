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

READY_JS = (
    "(function () {"
    " var name = document.getElementById('js_name');"
    " return document.readyState + '|' + (location.href || '') + '|' + (name ? 'has-name' : 'no-name');"
    "})();"
)

TRUE_JS = "true"


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
    lit = _as_literal(js)
    scripts = (
        "tell application \"Safari\"\n"
        "  activate\n"
        "  if (count of windows) is 0 then return \"no-window\"\n"
        f"  return do JavaScript {lit} in current tab of front window\n"
        "end tell\n",
        "tell application \"Safari\"\n"
        "  if (count of documents) is 0 then return \"no-document\"\n"
        f"  return do JavaScript {lit} in front document\n"
        "end tell\n",
    )
    last_error = "Safari JavaScript 失败"
    for source in scripts:
        try:
            out = _run_osascript(source, timeout=timeout, run=run)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
        if out in {"no-window", "no-document"}:
            last_error = out
            continue
        return out
    raise RuntimeError(last_error)


def open_in_safari(url: str, *, run: RunFn | None = None) -> None:
    runner = run or subprocess.run
    launch = runner(
        ["open", "-a", "Safari"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if launch.returncode != 0:
        err = (launch.stderr or launch.stdout or "").strip()
        raise RuntimeError(err or "无法启动 Safari")
    source = (
        "tell application \"Safari\"\n"
        "  activate\n"
        "  delay 0.4\n"
        "  if (count of windows) is 0 then\n"
        f"    make new document with properties {{URL:{_as_literal(url)}}}\n"
        "  else\n"
        "    tell front window\n"
        f"      set current tab to (make new tab with properties {{URL:{_as_literal(url)}}})\n"
        "    end tell\n"
        "  end if\n"
        "end tell\n"
    )
    try:
        _run_osascript(source, timeout=20, run=run)
    except Exception:
        proc = runner(
            ["open", "-a", "Safari", url],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(err or "无法用 Safari 打开文章") from None


def wait_safari_article(*, timeout_s: float = 40.0, run: RunFn | None = None) -> str:
    deadline = time.time() + timeout_s
    last = ""
    saw_page = False
    while time.time() < deadline:
        try:
            last = safari_do_javascript(READY_JS, run=run)
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(0.7)
            continue
        parts = last.split("|")
        state = parts[0] if parts else ""
        href = parts[1] if len(parts) > 1 else ""
        has_name = parts[2] if len(parts) > 2 else ""
        if "mp.weixin.qq.com" in href and "complete" in state:
            saw_page = True
            if has_name == "has-name":
                return last
        time.sleep(0.6)
    if saw_page:
        raise RuntimeError(
            f"文章已打开，但没有出现蓝字公众号名称 #js_name（{last}）。"
            "请确认打开的是公众号文章页，而不是登录页或验证码页。"
        )
    raise RuntimeError(f"Safari 文章页未就绪：{last}")


def click_system_go_button(*, run: RunFn | None = None) -> str:
    source = """
tell application "System Events"
  set procs to {"Safari", "微信", "WeChat", "Weixin"}
  repeat with procName in procs
    if exists process procName then
      tell process procName
        set frontmost to true
        delay 0.2
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
        "请在「系统设置 → 隐私与安全性 → 辅助功能」中允许 Terminal 以及 "
        "python.org 的 Python（或你启动 main.py 的那个解释器），"
        "并在 Safari「开发」菜单勾选「允许来自 Apple 事件的 JavaScript」。"
        "Safari 设置 → 高级 → 显示开发者功能 后才会出现开发菜单。"
    )


def probe_macos_automation(*, run: RunFn | None = None) -> list[str]:
    """Return human-readable problems; empty means the basic probes succeeded."""

    issues: list[str] = []
    if sys.platform != "darwin":
        return ["无人值守拉列表只支持 macOS"]
    try:
        _run_osascript(
            'tell application "System Events" to get name of first process',
            timeout=10,
            run=run,
        )
    except Exception:
        issues.append("辅助功能未授权（系统设置 → 隐私与安全性 → 辅助功能）")
    try:
        _run_osascript('tell application "Safari" to get name', timeout=10, run=run)
    except Exception:
        issues.append("无法控制 Safari（请先打开 Safari，并允许自动化控制）")
        return issues
    try:
        js_ok = safari_do_javascript(TRUE_JS, timeout=12, run=run)
        if str(js_ok).strip().lower() not in {"true", "1"}:
            issues.append("Safari 未允许来自 Apple 事件的 JavaScript（开发菜单）")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "no-window" in msg or "no-document" in msg:
            pass
        else:
            issues.append("Safari 未允许来自 Apple 事件的 JavaScript（开发菜单）")
    return issues


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
    sleep(1.0)
    ready = wait_safari_article(run=run)
    sleep(0.8)
    name_hit = "name-not-found"
    for _ in range(8):
        name_hit = safari_do_javascript(CLICK_NAME_JS, run=run)
        if name_hit.startswith("clicked"):
            break
        sleep(0.7)
    if not name_hit.startswith("clicked"):
        raise RuntimeError(
            f"未能点击文章页蓝字公众号名称（{name_hit}）。{accessibility_hint()}"
        )
    go_js = "go-not-found"
    ax = "skipped"
    for _ in range(10):
        sleep(0.5)
        go_js = safari_do_javascript(CLICK_GO_JS, run=run)
        if go_js.startswith("clicked"):
            break
    if not go_js.startswith("clicked"):
        ax = click_system_go_button(run=run)
        if not str(ax).startswith(("ax-clicked", "ax-sheet", "ax-window")):
            raise RuntimeError(
                f"已点击公众号名称，但没有点到「前往」（js={go_js}, ax={ax}）。"
                + accessibility_hint()
            )
    return {"ready": ready, "name": name_hit, "go_js": go_js, "go_ax": ax}
