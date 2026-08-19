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
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("status") or "") != "awaiting":
            continue
        aid = str(row.get("id") or "")
        if not aid:
            continue
        if listing_already_complete(cache, aid, days=days, date_range=date_range):
            continue
        if not str(row.get("article_url") or "").strip():
            continue
        out.append(row)
    return out
