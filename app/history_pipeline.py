"""List-then-archive pipeline with no GUI widgets.

getmsg listing needs the ~30-minute ``uin``/``key`` window.  Article HTML does
not, so this pipeline spends that window on paging only.  Bodies start after
the list is complete, or when the caller explicitly skips listing (expired
credentials + cached URLs).  The same output directory can be reused to skip
files already archived.
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
NowCallback = Callable[[], float]


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
    skip_listing: bool = False,
    cred_deadline_ts: float | None = None,
    fetch_history: Callable[..., dict[str, Any]] | None = None,
    archive: Callable[..., dict[str, Any]] | None = None,
    time_fn: NowCallback | None = None,
) -> dict[str, Any]:
    """List while credentials last; archive only when the list is ready.

    Listing uses the 30-minute getmsg window.  Article HTML does not need
    ``uin``/``key``, and expired cookies can even break public pages, so body
    fetches run without credentials.  If the window ends before the list is
    complete, URLs stay in cache and bodies wait for an explicit skip-listing
    run so the next capture can keep paging.
    """

    now = time_fn or time.time
    fetch = fetch_history or fetch_history_days
    archive_fn = archive or run_archive_job
    query_key = make_query_key(account_id, days=days, date_range=date_range)
    cached = cache.load(query_key)
    articles = list(cached.get("articles") or [])
    offset = 0 if cached.get("complete") else int(cached.get("next_offset") or 0)
    listing_complete = bool(cached.get("complete"))
    pages = 0
    t0 = now()
    listing_error = ""
    pagination_stalled = False
    cancelled = False

    def emit(payload: dict[str, Any]) -> None:
        if on_progress:
            on_progress(
                {
                    "articles": len(articles),
                    "pages": pages,
                    "elapsed_s": int(now() - t0),
                    "scope": _scope_label(days, date_range),
                    "out_dir": str(out_dir),
                    **payload,
                }
            )

    def listing_time_up() -> bool:
        return cred_deadline_ts is not None and now() >= float(cred_deadline_ts)

    if skip_listing or listing_complete:
        emit(
            {
                "stage": "listing",
                "status": "cached",
                "title": (
                    "跳过列表，直接归档已缓存正文"
                    if skip_listing
                    else "列表已在本地缓存中，直接归档正文"
                ),
            }
        )
    else:
        while True:
            if should_cancel and should_cancel():
                cancelled = True
                listing_error = "已取消"
                break
            if listing_time_up():
                listing_error = "凭证窗口即将结束，列表已缓存；请续约后继续拉列表。"
                emit(
                    {
                        "stage": "listing",
                        "status": "cred_window",
                        "title": listing_error,
                    }
                )
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
        "elapsed_s": int(now() - t0),
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

    # Bodies do not need the 30-minute window.  Do not start a multi-hour
    # download while the list is still incomplete: the next capture should
    # keep paging.  Expired-credential runs pass skip_listing=True.
    if not (skip_listing or listing_complete):
        emit(
            {
                "stage": "done",
                "status": "list_paused",
                "title": listing_error
                or "列表未拉完，已写入缓存。请续约后继续拉列表；正文可在凭证过期后单独归档。",
            }
        )
        return summary

    emit(
        {
            "stage": "archiving",
            "status": "archiving",
            "title": f"列表 {len(articles)} 篇，开始拉取正文（不使用凭证）",
        }
    )
    archive_result = archive_fn(
        articles,
        account_name=account_name,
        out_dir=out_dir,
        fmt=fmt,
        cred=None,
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
    summary["elapsed_s"] = int(now() - t0)
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
