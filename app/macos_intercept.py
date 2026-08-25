"""Diagnose why macOS local capture sees no WeChat traffic."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REDIRECTOR_BUNDLE = "org.mitmproxy.macos-redirector"
WECHAT_NAME_KEYS = ("WeChat", "Weixin", "微信")


def parse_redirector_state(text: str) -> str:
    """Return waiting_for_user | enabled | terminated | present | missing."""
    found = False
    for line in text.splitlines():
        if REDIRECTOR_BUNDLE not in line:
            continue
        found = True
        lower = line.lower()
        if "waiting for user" in lower:
            return "waiting_for_user"
        if "activated enabled" in lower or "[activated enabled]" in lower:
            return "enabled"
        if "terminated" in lower:
            return "terminated"
    return "present" if found else "missing"


def redirector_state() -> str:
    if sys.platform != "darwin":
        return "n/a"
    try:
        proc = subprocess.run(
            ["systemextensionsctl", "list"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return "unknown"
    return parse_redirector_state((proc.stdout or "") + "\n" + (proc.stderr or ""))


def clash_meta_running() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        proc = subprocess.run(
            ["pgrep", "-f", "/Applications/ClashX Meta.app"],
            capture_output=True,
            timeout=5,
        )
        return proc.returncode == 0
    except Exception:
        return False


def wechat_pids() -> list[str]:
    if sys.platform != "darwin":
        return []
    try:
        out = subprocess.check_output(["ps", "-axo", "pid=,comm="], text=True, timeout=5)
    except Exception:
        return []
    pids: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid, _, comm = line.partition(" ")
        comm = comm.strip()
        if "Cursor" in comm:
            continue
        base = Path(comm).name
        if any(key in comm or key in base for key in WECHAT_NAME_KEYS):
            if pid.isdigit():
                pids.append(pid)
    return pids


def wechat_intercept_spec(base_names: str) -> str:
    extra = wechat_pids()
    if not extra:
        return base_names
    return base_names + "," + ",".join(extra)


def capture_warnings() -> list[str]:
    if sys.platform != "darwin":
        return []
    warnings: list[str] = []
    state = redirector_state()
    if state == "waiting_for_user":
        warnings.append(
            "【拦截未生效】mitmproxy 网络扩展仍是「等待用户批准」。"
            "请打开：系统设置 → 通用 → 登录项与扩展 → 网络扩展，打开 Mitmproxy Redirector；"
            "然后完全退出微信再打开。不批准的话续约永远抓不到流量。"
        )
    elif state in {"missing", "terminated"}:
        warnings.append(
            "未启用 Mitmproxy Redirector 网络扩展。请点「批准微信拦截」，并在系统设置里打开它。"
        )
    if clash_meta_running():
        warnings.append(
            "检测到 ClashX Meta。请先退出 Clash，或关闭增强模式 / TUN，否则微信流量会被它抢走。"
        )
    return warnings


def open_redirector_approval() -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, "仅 macOS 需要批准网络扩展"
    try:
        subprocess.Popen(["open", "-a", "Mitmproxy Redirector"])
    except Exception:
        pass
    try:
        subprocess.Popen(
            [
                "open",
                "x-apple.systempreferences:com.apple.LoginItems-Settings.extension",
            ]
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"无法打开系统设置：{exc}"
    return True, (
        "已打开 Mitmproxy Redirector 和系统设置。"
        "请在「登录项与扩展 → 网络扩展」中打开拦截，然后完全退出并重启微信。"
    )
