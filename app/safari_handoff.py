"""Open a WeChat article in Safari and hand it off to WeChat Desktop.

The article page's blue account name (#js_name, under the title) must be
clicked; that shows 「即将前往微信打开此文章」.  Then 「前往」 must be clicked.

That confirm UI is usually a **Safari system sheet**, not a DOM button.
JavaScript cannot press it.  Accessibility + Return are required.
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
    " function forceClick(el) {"
    "  if (!el) return;"
    "  try { el.focus(); } catch (e1) {}"
    "  ['pointerdown','mousedown','touchstart','pointerup','mouseup','touchend','click'].forEach(function (type) {"
    "   try {"
    "    var ev = type.indexOf('touch') === 0"
    "      ? new Event(type, {bubbles:true,cancelable:true})"
    "      : new MouseEvent(type, {bubbles:true,cancelable:true,view:window,buttons:1});"
    "    el.dispatchEvent(ev);"
    "   } catch (e2) {}"
    "  });"
    "  try { el.click(); } catch (e3) {}"
    " }"
    " function docsOf(win) {"
    "  var out = [];"
    "  try { out.push(win.document); } catch (e4) { return out; }"
    "  var frames = win.document.querySelectorAll('iframe');"
    "  for (var i = 0; i < frames.length; i++) {"
    "   try { out = out.concat(docsOf(frames[i].contentWindow)); } catch (e5) {}"
    "  }"
    "  return out;"
    " }"
    " var docs = docsOf(window);"
    " for (var d = 0; d < docs.length; d++) {"
    "  var doc = docs[d];"
    "  var primary = doc.querySelector("
    "   '.weui-dialog__btn_primary, a.weui-dialog__btn_primary,"
    "    .weui-dialog__btn.weui-dialog__btn_primary, .weui-half-screen-dialog__btn_primary'"
    "  );"
    "  if (primary) { forceClick(primary); return 'clicked-primary'; }"
    "  var nodes = doc.querySelectorAll('a, button, span, div, input');"
    "  for (var i = 0; i < nodes.length; i++) {"
    "   var t = (nodes[i].innerText || nodes[i].textContent || '').replace(/\\s+/g, ' ').trim();"
    "   if (t === '前往' || t === '打开') {"
    "    var target = nodes[i].closest('a, button, .weui-dialog__btn') || nodes[i];"
    "    forceClick(target);"
    "    return 'clicked-go';"
    "   }"
    "  }"
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

WECHAT_PROCESS_NAMES = ("微信", "WeChat", "Weixin")

# Measured by the operator with Safari in fullscreen: the 「前往」 button.
GO_BUTTON_POINT = (958, 640)


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


def frontmost_app_name(*, run: RunFn | None = None) -> str:
    try:
        return _run_osascript(
            'tell application "System Events" to get name of first process whose frontmost is true',
            timeout=8,
            run=run,
        )
    except Exception:
        return ""


def is_wechat_app(name: str) -> bool:
    text = (name or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return text in WECHAT_PROCESS_NAMES or "wechat" in lowered or "weixin" in lowered or "微信" in text


def ensure_safari_fullscreen(*, run: RunFn | None = None) -> str:
    """GO_BUTTON_POINT was measured in fullscreen; keep Safari in that layout."""

    source = """
tell application "Safari" to activate
delay 0.2
tell application "System Events"
  if not (exists process "Safari") then return "no-safari"
  tell process "Safari"
    set frontmost to true
    delay 0.1
    try
      if (count of windows) is 0 then return "no-window"
      set fs to false
      try
        set fs to value of attribute "AXFullScreen" of window 1
      end try
      if fs is true then return "already-fullscreen"
      try
        set value of attribute "AXFullScreen" of window 1 to true
        delay 0.8
        return "entered-fullscreen"
      end try
    end try
  end tell
end tell
return "fullscreen-unknown"
"""
    try:
        return _run_osascript(source, timeout=12, run=run)
    except Exception as exc:  # noqa: BLE001
        return f"fullscreen-error:{exc}"


def _main_display_height_points(*, run: RunFn | None = None) -> int:
    source = (
        'use framework "AppKit"\n'
        "use scripting additions\n"
        "set h to (current application's NSScreen's mainScreen's "
        "frame()'s |size|'s height) as number\n"
        "return h as integer\n"
    )
    try:
        return int(float(_run_osascript(source, timeout=8, run=run)))
    except Exception:
        return 1080


def _quartz_click(x: float, y: float) -> None:
    """Post a left click. Quartz uses a bottom-left origin."""

    import ctypes
    import ctypes.util

    cg_path = ctypes.util.find_library("CoreGraphics") or (
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    )
    cf_path = ctypes.util.find_library("CoreFoundation") or (
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
    cg = ctypes.cdll.LoadLibrary(cg_path)
    cf = ctypes.cdll.LoadLibrary(cf_path)

    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    k_cg_event_left_mouse_down = 1
    k_cg_event_left_mouse_up = 2
    k_cg_hid_event_tap = 0
    k_cg_mouse_button_left = 0

    create = cg.CGEventCreateMouseEvent
    create.restype = ctypes.c_void_p
    create.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
    post = cg.CGEventPost
    post.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    release = cf.CFRelease
    release.argtypes = [ctypes.c_void_p]

    point = CGPoint(x, y)
    down = create(None, k_cg_event_left_mouse_down, point, k_cg_mouse_button_left)
    up = create(None, k_cg_event_left_mouse_up, point, k_cg_mouse_button_left)
    if down:
        post(k_cg_hid_event_tap, down)
    if up:
        post(k_cg_hid_event_tap, up)
    if down:
        release(down)
    if up:
        release(up)


def click_screen_point(
    x: int,
    y: int,
    *,
    run: RunFn | None = None,
) -> str:
    """Click a top-left screen point. 958,640 is 「前往」 in fullscreen Safari."""

    if run is None:
        try:
            height = _main_display_height_points()
            _quartz_click(float(x), float(height - y))
        except Exception:
            pass
    source = (
        "tell application \"Safari\" to activate\n"
        "delay 0.05\n"
        "tell application \"System Events\"\n"
        "  tell process \"Safari\"\n"
        "    set frontmost to true\n"
        "  end tell\n"
        "  delay 0.05\n"
        f"  click at {{{int(x)}, {int(y)}}}\n"
        "end tell\n"
        f'return "xy:{int(x)},{int(y)}"\n'
    )
    try:
        out = _run_osascript(source, timeout=8, run=run)
        if str(out).startswith("xy:"):
            return out
        return f"xy:{int(x)},{int(y)}"
    except Exception as exc:  # noqa: BLE001
        if run is None:
            return f"xy:{int(x)},{int(y)}:quartz-only:{exc}"
        return f"xy-error:{exc}"


def safari_has_sheet(*, run: RunFn | None = None) -> bool:
    source = """
tell application "System Events"
  if not (exists process "Safari") then return "no-safari"
  tell process "Safari"
    if (count of windows) is 0 then return "no-window"
    try
      if (count of sheets of window 1) > 0 then return "has-sheet"
    end try
    return "no-sheet"
  end tell
end tell
"""
    try:
        return _run_osascript(source, timeout=8, run=run) == "has-sheet"
    except Exception:
        return False


def press_safari_confirm_key(*, run: RunFn | None = None) -> str:
    """Return activates the default (right-hand) button on a Safari sheet."""

    source = """
tell application "Safari" to activate
delay 0.15
tell application "System Events"
  if not (exists process "Safari") then return "no-safari"
  tell process "Safari"
    set frontmost to true
    delay 0.1
    try
      if (count of sheets of window 1) > 0 then
        key code 36
        return "return-sheet"
      end if
    end try
  end tell
end tell
return "no-sheet"
"""
    try:
        return _run_osascript(source, timeout=10, run=run)
    except Exception as exc:  # noqa: BLE001
        return f"return-error:{exc}"


def click_system_go_button(*, run: RunFn | None = None) -> str:
    """Click Safari's native 「前往」/「打开」 sheet, then fall back to a deep search."""

    source = """
tell application "Safari" to activate
delay 0.12
tell application "System Events"
  set targetNames to {"前往", "打开", "Open", "Go", "OK", "好"}
  set procNames to {"Safari", "微信", "WeChat", "Weixin"}
  repeat with procName in procNames
    set pName to procName as text
    if exists process pName then
      tell process pName
        set frontmost to true
        delay 0.12
        try
          if (count of sheets of window 1) > 0 then
            tell sheet 1 of window 1
              repeat with nm in targetNames
                try
                  click (first button whose name is (nm as text))
                  return "ax-sheet-name:" & pName & ":" & (nm as text)
                end try
              end repeat
              try
                click button 2
                return "ax-sheet-btn2:" & pName
              end try
              try
                click (last button)
                return "ax-sheet-last:" & pName
              end try
              try
                tell group 1
                  repeat with nm in targetNames
                    try
                      click (first button whose name is (nm as text))
                      return "ax-sheet-group:" & pName & ":" & (nm as text)
                    end try
                  end repeat
                  try
                    click button 2
                    return "ax-sheet-group-btn2:" & pName
                  end try
                end tell
              end try
            end tell
          end if
        end try
        try
          tell window 1
            repeat with nm in targetNames
              try
                click (first button whose name is (nm as text))
                return "ax-window-name:" & pName & ":" & (nm as text)
              end try
            end repeat
          end tell
        end try
        try
          repeat with nm in targetNames
            try
              click (first button whose name is (nm as text))
              return "ax-process-name:" & pName & ":" & (nm as text)
            end try
          end repeat
        end try
      end tell
    end if
  end repeat
end tell
return "ax-miss"
"""
    try:
        return _run_osascript(source, timeout=20, run=run)
    except Exception as exc:  # noqa: BLE001
        return f"ax-error:{exc}"


def dump_safari_buttons(*, run: RunFn | None = None) -> str:
    source = """
tell application "System Events"
  if not (exists process "Safari") then return "no-safari"
  tell process "Safari"
    set out to ""
    try
      set out to out & "window:" & (name of window 1 as text) & ";"
    end try
    try
      if (count of sheets of window 1) > 0 then
        set out to out & "sheet-buttons:"
        repeat with b in buttons of sheet 1 of window 1
          try
            set out to out & "[" & (name of b as text) & "]"
          end try
        end repeat
      else
        set out to out & "no-sheet;"
      end if
    end try
    try
      set out to out & "win-buttons:"
      repeat with b in buttons of window 1
        try
          set out to out & "[" & (name of b as text) & "]"
        end try
      end repeat
    end try
    return out
  end tell
end tell
"""
    try:
        return _run_osascript(source, timeout=10, run=run)
    except Exception as exc:  # noqa: BLE001
        return f"dump-error:{exc}"


def accessibility_hint() -> str:
    return (
        "请在「系统设置 → 隐私与安全性 → 辅助功能」中允许 Terminal 以及 "
        "python.org 的 Python（或你启动 main.py 的那个解释器），"
        "并在 Safari「开发」菜单勾选「允许来自 Apple 事件的 JavaScript」。"
        "Safari 设置 → 高级 → 显示开发者功能 后才会出现开发菜单。"
        "「前往」是 Safari 系统弹窗，不是网页按钮，必须打开辅助功能才能点到。"
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


def _ax_clicked(result: str) -> bool:
    return str(result).startswith("ax-") and not str(result).startswith(
        ("ax-miss", "ax-error")
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
    sleep(1.0)
    ready = wait_safari_article(run=run)
    fullscreen = ensure_safari_fullscreen(run=run)
    sleep(0.6)
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

    wechat_before = is_wechat_app(frontmost_app_name(run=run))
    go_js = "go-not-found"
    ax = "skipped"
    key_hit = "skipped"
    xy = "skipped"
    sheet = False
    handed_off = False
    go_x, go_y = GO_BUTTON_POINT

    # 「前往」 is a Safari system dialog at 958,640 in fullscreen.
    sleep(0.6)
    xy = click_screen_point(go_x, go_y, run=run)
    sleep(0.45)
    xy = click_screen_point(go_x, go_y, run=run)
    sheet = safari_has_sheet(run=run)
    if sheet:
        ax = click_system_go_button(run=run)
        if not _ax_clicked(ax):
            key_hit = press_safari_confirm_key(run=run)
    else:
        try:
            go_js = safari_do_javascript(CLICK_GO_JS, run=run)
        except Exception as exc:  # noqa: BLE001
            go_js = f"js-error:{exc}"
        ax = click_system_go_button(run=run)
    wechat_now = is_wechat_app(frontmost_app_name(run=run))
    if wechat_now and not wechat_before:
        handed_off = True
    if _ax_clicked(ax) or key_hit.startswith("return-sheet"):
        handed_off = True
    if str(xy).startswith("xy:") and not str(xy).startswith("xy-error"):
        handed_off = True
    if str(go_js).startswith("clicked") and not safari_has_sheet(run=run):
        handed_off = True

    if not handed_off:
        dump = dump_safari_buttons(run=run)
        raise RuntimeError(
            f"已点击公众号名称，但没有点到「前往」"
            f"（js={go_js}, ax={ax}, key={key_hit}, xy={xy}, sheet={sheet},"
            f" fullscreen={fullscreen}, buttons={dump}）。"
            + accessibility_hint()
        )
    return {
        "ready": ready,
        "name": name_hit,
        "go_js": go_js,
        "go_ax": ax,
        "go_key": key_hit,
        "go_xy": xy,
        "fullscreen": fullscreen,
    }
