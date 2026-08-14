"""List-then-archive pipeline with no GUI widgets.

Paging continues automatically while WeChat still advances ``next_offset``.
Article bodies are written immediately after the list is as complete as this
session can make it.  The same output directory can be reused to skip files
already archived.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from app.archive_job import run_archive_job
from app.history_cache import HistoryCache, make_query_key
from app.history_client import fetch_history_days

ProgressCallback = Callable[[dict[str, Any]], None]
CancelCallback = Callable[[], bool]


def _scope_label(
    days: int | None,
    date_range: tuple[str, str] | None,
) -> str:
    if date_range:
        return f"{date_range[0]} 至 {date_range[1]}"
    return "全部历史" if days is None else f"近 {days} 天"


def run_list_and_archive(
    cred: dict[str, Any],
    *,
    account_id: str,
    account_name: str,
    cache: HistoryCache,
    days: int | None,
    date_range: tuple[str, str] | None,
    start_ts: int | None,
    end_ts: int | None,
    sightings: list[dict[str, Any]] | None,
    out_dir: Path | str,
    fmt: str = "markdown",
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    max_pages_per_batch: int = 100,
    batch_pause_s: float = 1.0,
    fetch_history: Callable[..., dict[str, Any]] | None = None,
    archive: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch every history page, then archive every article body.

    Does not create Tk widgets.  Pagination authority remains advancing
    ``next_offset``; ``can_msg_continue=false`` is not treated as completion.
    """

    fetch = fetch_history or fetch_history_days
    archive_fn = archive or run_archive_job
    query_key = make_query_key(account_id, days=days, date_range=date_range)
    cached = cache.load(query_key)
    articles = list(cached.get("articles") or [])
    offset = 0 if cached.get("complete") else int(cached.get("next_offset") or 0)
    listing_complete = bool(cached.get("complete"))
    pages = 0
    t0 = time.time()
    listing_error = ""
    pagination_stalled = False
    cancelled = False

    def emit(payload: dict[str, Any]) -> None:
        if on_progress:
            on_progress(
                {
                    "articles": len(articles),
                    "pages": pages,
                    "elapsed_s": int(time.time() - t0),
                    "scope": _scope_label(days, date_range),
                    "out_dir": str(out_dir),
                    **payload,
                }
            )

    if listing_complete:
        emit(
            {
                "stage": "listing",
                "status": "cached",
                "title": "列表已在本地缓存中，直接归档正文",
            }
        )
    else:
        while True:
            if should_cancel and should_cancel():
                cancelled = True
                listing_error = "已取消"
                break
            emit(
                {
                    "stage": "listing",
                    "status": "fetching",
                    "offset": offset,
                    "title": f"正在拉取列表 offset={offset}",
                }
            )
            result = fetch(
                cred,
                days=days,
                max_pages=max_pages_per_batch,
                on_progress=None,
                sightings=sightings,
                should_cancel=should_cancel,
                start_ts=start_ts,
                end_ts=end_ts,
                start_offset=offset,
            )
            pages += int(result.get("pages") or 0)
            pagination_stalled = bool(result.get("pagination_stalled"))
            batch_complete = bool(
                result.get("ok")
                and not result.get("hit_page_cap")
                and not result.get("cancelled")
            )
            next_offset = 0 if batch_complete else int(result.get("next_offset") or offset)
            cache.save_batch(
                query_key,
                account_id=account_id,
                account_name=account_name,
                days=days,
                date_range=date_range,
                articles=list(result.get("articles") or []),
                next_offset=next_offset,
                complete=batch_complete,
            )
            loaded = cache.load(query_key)
            articles = list(loaded.get("articles") or [])
            offset = 0 if loaded.get("complete") else int(loaded.get("next_offset") or 0)
            listing_complete = bool(loaded.get("complete"))

            if result.get("cancelled") or (should_cancel and should_cancel()):
                cancelled = True
                listing_error = "已取消"
                break
            if not result.get("ok"):
                listing_error = str(result.get("error") or "getmsg 失败")
                break
            if result.get("hit_page_cap"):
                if batch_pause_s:
                    time.sleep(batch_pause_s)
                continue
            break

    summary: dict[str, Any] = {
        "account": account_name,
        "scope": _scope_label(days, date_range),
        "articles": len(articles),
        "pages": pages,
        "elapsed_s": int(time.time() - t0),
        "listing_complete": listing_complete,
        "pagination_stalled": pagination_stalled,
        "listing_error": listing_error,
        "cancelled": cancelled,
        "archive": None,
        "out_dir": str(out_dir),
    }
    if cancelled:
        emit({"stage": "cancelled", "status": "cancelled", "title": listing_error})
        return summary
    if not articles:
        emit(
            {
                "stage": "done",
                "status": "empty",
                "title": listing_error or "没有可归档的文章",
            }
        )
        return summary

    emit(
        {
            "stage": "archiving",
            "status": "archiving",
            "title": f"列表 {len(articles)} 篇，开始拉取正文",
        }
    )
    archive_result = archive_fn(
        articles,
        account_name=account_name,
        out_dir=out_dir,
        fmt=fmt,
        cred=cred,
        on_progress=lambda event: emit(
            {
                "stage": "archiving",
                "status": event.get("status") or "archiving",
                "title": str(event.get("title") or ""),
                "ok": event.get("ok") or 0,
                "failed": event.get("failed") or 0,
                "skipped": event.get("skipped") or 0,
                "retries": event.get("retries") or 0,
                "current": event.get("current") or 0,
                "total": event.get("total") or len(articles),
            }
        ),
        should_cancel=should_cancel,
    )
    summary["archive"] = archive_result
    summary["elapsed_s"] = int(time.time() - t0)
    if archive_result.get("cancelled"):
        summary["cancelled"] = True
        emit({"stage": "cancelled", "status": "cancelled", "title": "已停止正文归档"})
        return summary
    emit(
        {
            "stage": "done",
            "status": "done",
            "ok": archive_result.get("ok") or 0,
            "failed": archive_result.get("failed") or 0,
            "skipped": archive_result.get("skipped") or 0,
            "title": "完成",
        }
    )
    return summary
