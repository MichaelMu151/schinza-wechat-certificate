"""Unattended list-only queue: capture one awaiting account, page getmsg, next.

Does not download article bodies.  Does not delete accounts.  Stops the whole
queue on WeChat rate-limit errors.
"""

from __future__ import annotations

from typing import Any, Callable

from app.history_cache import HistoryCache, make_query_key

ProgressFn = Callable[[str, bool | None], None]
CancelFn = Callable[[], bool]


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
) -> list[dict[str, Any]]:
    """Active accounts with leftover credential time are listed first (no Safari).

    Awaiting accounts still need the Safari → 前往 → WeChat capture step.
    Already-complete lists are skipped.  Cards are never deleted.
    """

    active_items: list[dict[str, Any]] = []
    awaiting_items: list[dict[str, Any]] = []
    for row in rows:
        aid = str(row.get("id") or "")
        if not aid:
            continue
        if listing_already_complete(cache, aid, days=days, date_range=date_range):
            continue
        status = str(row.get("status") or "")
        url = str(row.get("article_url") or "").strip()
        if status == "active":
            active_items.append({"row": row, "need_handoff": False})
        elif status == "awaiting":
            if not url:
                continue
            awaiting_items.append({"row": row, "need_handoff": True})
    return active_items + awaiting_items
