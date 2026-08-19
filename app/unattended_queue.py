"""Unattended per-account queue: finish listing, then bodies, then next.

Does not delete accounts.  Stops the whole queue on WeChat rate-limit errors.
Listing for one account continues across credential windows (Safari recapture)
until complete; article bodies start only after that list is complete.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from app.history_cache import HistoryCache, make_query_key

ProgressFn = Callable[[str, bool | None], None]
CancelFn = Callable[[], bool]

MAX_LISTING_ROUNDS = 24
MIN_CRED_SECONDS_TO_PAGE = 90


def is_rate_limit_listing_error(error: str) -> bool:
    text = (error or "").lower()
    needles = (
        "unknownerror",
        "unknown error",
        "429",
        "频繁",
        "freq control",
        "rate_limited",
        "风控",
    )
    return any(n in text for n in needles)


def listing_already_complete(
    cache: HistoryCache,
    account_id: str,
    *,
    days: int | None,
    date_range: tuple[str, str] | None,
) -> bool:
    key = make_query_key(account_id, days=days, date_range=date_range)
    return bool(cache.load(key).get("complete"))


def safe_archive_dirname(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name or "公众号")[:60]


def bodies_already_done(
    cache: HistoryCache,
    account_id: str,
    *,
    days: int | None,
    date_range: tuple[str, str] | None,
    out_dir: Path,
) -> bool:
    if not listing_already_complete(cache, account_id, days=days, date_range=date_range):
        return False
    key = make_query_key(account_id, days=days, date_range=date_range)
    articles = list(cache.load(key).get("articles") or [])
    if not articles:
        return True
    index_path = Path(out_dir) / "archive_index.sqlite"
    if not index_path.is_file():
        return False
    from app.archive_job import ArchiveIndex, article_identity

    done = ArchiveIndex(index_path).completed_paths()
    for row in articles:
        ident = article_identity(row)
        path = Path(done.get(ident) or "")
        if not path.is_file():
            return False
    return True


def should_stay_on_account(result: dict[str, Any]) -> bool:
    """True when listing is incomplete and we should recapture the same account."""

    if result.get("cancelled"):
        return False
    if is_rate_limit_listing_error(str(result.get("listing_error") or "")):
        return False
    archive = result.get("archive") or {}
    if isinstance(archive, dict) and archive.get("paused_rate_limit"):
        return False
    return not bool(result.get("listing_complete"))


def select_awaiting_accounts(
    rows: list[dict[str, Any]],
    cache: HistoryCache,
    *,
    days: int | None,
    date_range: tuple[str, str] | None,
) -> list[dict[str, Any]]:
    return [
        item["row"]
        for item in select_unattended_queue(rows, cache, days=days, date_range=date_range)
        if item["need_handoff"]
    ]


def select_unattended_queue(
    rows: list[dict[str, Any]],
    cache: HistoryCache,
    *,
    days: int | None,
    date_range: tuple[str, str] | None,
    archives_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Build the unattended queue: finish one account (list then bodies) before the next.

    Active accounts with leftover listing work come first (no Safari).  Awaiting
    accounts still need Safari → 前往.  Accounts whose lists are already complete
    but whose bodies are unfinished are appended last.  Cards are never deleted.
    """

    active_items: list[dict[str, Any]] = []
    awaiting_items: list[dict[str, Any]] = []
    bodies_only_items: list[dict[str, Any]] = []
    for row in rows:
        aid = str(row.get("id") or "")
        if not aid:
            continue
        name = str(row.get("name") or "")
        out_dir = (
            Path(archives_root) / safe_archive_dirname(name)
            if archives_root is not None
            else None
        )
        list_done = listing_already_complete(cache, aid, days=days, date_range=date_range)
        if list_done:
            if archives_root is None or (
                out_dir is not None
                and bodies_already_done(
                    cache, aid, days=days, date_range=date_range, out_dir=out_dir
                )
            ):
                continue
            bodies_only_items.append(
                {"row": row, "need_handoff": False, "skip_listing": True}
            )
            continue
        status = str(row.get("status") or "")
        url = str(row.get("article_url") or "").strip()
        if status == "active":
            active_items.append({"row": row, "need_handoff": False, "skip_listing": False})
        elif status == "awaiting":
            if not url:
                continue
            awaiting_items.append({"row": row, "need_handoff": True, "skip_listing": False})
    return active_items + awaiting_items + bodies_only_items
