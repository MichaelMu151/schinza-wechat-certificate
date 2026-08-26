"""Resumable, low-rate whole-account article archiving.

This module deliberately has no GUI dependency.  It writes each successful
article immediately and appends a small state event, so a stopped job can be
resumed without downloading completed articles again.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import requests

from app.article_reader import (
    extension_for_article_format,
    fetch_and_parse_article,
    safe_export_filename,
    write_article_export,
)
from app.errors import describe_exception

ProgressCallback = Callable[[dict[str, Any]], None]
CancelCallback = Callable[[], bool]


def article_identity(article: dict[str, Any]) -> str:
    identity = str(article.get("identity") or "").strip()
    if identity:
        return identity
    link = str(article.get("link") or "").strip()
    try:
        query = parse_qs(urlparse(link).query)
    except ValueError:
        query = {}
    mid = str((query.get("mid") or [""])[0])
    idx = str((query.get("idx") or [""])[0])
    sn = str((query.get("sn") or [""])[0])
    if mid:
        return f"mid:{mid}|idx:{idx or '1'}|sn:{sn}"
    return link or (
        f"title:{article.get('title')}|publish:{article.get('publish_ts') or ''}"
    )


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()


def _load_latest_states(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        identity = str(event.get("identity") or "")
        if identity:
            latest[identity] = event
    return latest


def _write_manifest(
    out_dir: Path,
    *,
    account_name: str,
    articles: list[dict[str, Any]],
    fmt: str,
) -> Path:
    path = out_dir / "manifest.json"
    jsonl_path = out_dir / "manifest.jsonl"
    jsonl_tmp = jsonl_path.with_suffix(".jsonl.tmp")
    with jsonl_tmp.open("w", encoding="utf-8") as handle:
        for article in articles:
            handle.write(json.dumps(article, ensure_ascii=False) + "\n")
    jsonl_tmp.replace(jsonl_path)
    payload = {
        "account": account_name,
        "count": len(articles),
        "format": fmt,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "articles_file": jsonl_path.name,
    }
    # Keep the legacy single-file shape for ordinary accounts.  Very large
    # histories use JSONL to avoid building/writing a huge nested JSON object.
    if len(articles) <= 10_000:
        payload["articles"] = articles
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


class ArchiveIndex:
    """Compact resume index; JSONL files remain human-readable audit logs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS archive_articles (
                    identity TEXT PRIMARY KEY,
                    article_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    path TEXT,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                );
                CREATE INDEX IF NOT EXISTS idx_archive_status
                    ON archive_articles(status, identity);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def seed(self, articles: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            for article in articles:
                identity = article_identity(article)
                conn.execute(
                    """
                    INSERT INTO archive_articles (identity, article_json)
                    VALUES (?, ?)
                    ON CONFLICT(identity) DO UPDATE SET
                        article_json=excluded.article_json
                    """,
                    (identity, json.dumps(article, ensure_ascii=False)),
                )

    def completed_paths(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT identity, path FROM archive_articles WHERE status='ok'"
            ).fetchall()
        return {str(row["identity"]): str(row["path"] or "") for row in rows}

    def record(
        self,
        identity: str,
        *,
        status: str,
        path: str = "",
        error: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE archive_articles
                SET status=?, path=NULLIF(?, ''), error=NULLIF(?, ''),
                    attempts=attempts+1,
                    updated_at=datetime('now','localtime')
                WHERE identity=?
                """,
                (status, path, error, identity),
            )


def _looks_rate_limited(parsed: dict[str, Any]) -> bool:
    sample = " ".join(
        str(parsed.get(key) or "")[:1000]
        for key in ("title", "content_text", "text", "error")
    ).lower()
    return any(
        marker in sample
        for marker in (
            "访问过于频繁",
            "请求过于频繁",
            "操作频繁",
            "unknownerror",
            "too many requests",
            "rate limit",
        )
    )


def _is_rate_limit_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else 0
        if status == 429:
            return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("unknownerror", "频繁", "too many requests", "rate limit", "429")
    )


def _is_transient_error(exc: Exception) -> bool:
    """Return whether a short retry is safer than recording a final failure."""
    if _is_rate_limit_error(exc):
        return False
    if isinstance(exc, requests.exceptions.RequestException):
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "timeout",
            "timed out",
            "connection",
            "reset",
            "temporarily unavailable",
            "bad gateway",
            "service unavailable",
            "502",
            "503",
            "504",
        )
    )


def run_archive_job(
    articles: list[dict[str, Any]],
    *,
    account_name: str,
    out_dir: Path | str,
    fmt: str = "markdown",
    cred: dict[str, Any] | None = None,
    fetch_article: Callable[..., dict[str, Any]] | None = None,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    sleep_min_s: float = 8.0,
    sleep_max_s: float = 15.0,
    max_workers: int = 1,
    transient_retries: int = 2,
    retry_backoff_s: tuple[float, float] = (12.0, 30.0),
    cooldown_after_failures: int = 3,
    cooldown_range_s: tuple[float, float] = (60.0, 120.0),
) -> dict[str, Any]:
    """Archive sequentially: completeness first, one request, 8–15 s apart."""

    output = Path(out_dir)
    article_dir = output / "articles"
    article_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = _write_manifest(
        output, account_name=account_name, articles=articles, fmt=fmt
    )
    state_path = output / "job_state.jsonl"
    failure_path = output / "failures.jsonl"
    archive_index = ArchiveIndex(output / "archive_index.sqlite")
    archive_index.seed(articles)
    latest = _load_latest_states(state_path)
    completed_paths = archive_index.completed_paths()
    # Migrate successful runs made before archive_index.sqlite was introduced.
    for identity, event in latest.items():
        path = str(event.get("path") or "")
        if (
            identity not in completed_paths
            and event.get("status") == "ok"
            and Path(path).is_file()
        ):
            archive_index.record(identity, status="ok", path=path)
            completed_paths[identity] = path
    fetch = fetch_article or fetch_and_parse_article
    ext = extension_for_article_format(fmt)
    total = len(articles)
    completed = failed = skipped = retries = 0
    paused = cancelled = False
    consecutive_failures = 0

    pending: list[tuple[int, dict[str, Any], str, str, str]] = []
    for index, row in enumerate(articles, start=1):
        identity = article_identity(row)
        title = str(row.get("title") or f"article_{index}").strip()
        previous_path = Path(completed_paths.get(identity) or "")
        if previous_path.is_file():
            skipped += 1
            if on_progress:
                on_progress(
                    {
                        "current": index,
                        "total": total,
                        "ok": completed,
                        "failed": failed,
                        "skipped": skipped,
                        "title": title,
                        "status": "skipped",
                    }
                )
            continue
        link = str(row.get("link") or "").strip()
        if not link:
            failed += 1
            event_base = {
                "time": datetime.now().isoformat(timespec="seconds"),
                "identity": identity,
                "index": index,
                "title": title,
                "link": link,
            }
            event = {**event_base, "status": "failed", "error": "无链接"}
            _append_jsonl(state_path, event)
            _append_jsonl(failure_path, event)
            archive_index.record(identity, status="failed", error="无链接")
            continue
        pending.append((index, row, identity, title, link))

    def fetch_one(
        entry: tuple[int, dict[str, Any], str, str, str]
    ) -> tuple[dict[str, Any], int]:
        _index, _row, _identity, _title, link = entry
        attempts = 0
        while True:
            try:
                parsed = fetch(link, cred=cred)
                if _looks_rate_limited(parsed):
                    raise RuntimeError("微信返回访问过于频繁页面")
                return parsed, attempts
            except Exception as exc:
                if (
                    attempts >= max(0, int(transient_retries))
                    or not _is_transient_error(exc)
                    or (should_cancel and should_cancel())
                ):
                    raise
                attempts += 1
                low, high = retry_backoff_s
                low = max(0.0, float(low)) * attempts
                high = max(low, float(high) * attempts)
                time.sleep(random.uniform(low, high))

    worker_count = 1
    for pending_index, entry in enumerate(pending):
        if should_cancel and should_cancel():
            cancelled = True
            break
        index, row, identity, title, link = entry
        if on_progress:
            on_progress(
                {
                    "current": index,
                    "total": total,
                    "ok": completed,
                    "failed": failed,
                    "skipped": skipped,
                    "retries": retries,
                    "title": title,
                    "status": "fetching",
                }
            )
        event_base = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "identity": identity,
            "index": index,
            "title": title,
            "link": link,
        }
        try:
            parsed, used_retries = fetch_one(entry)
            retries += used_retries
            if not parsed.get("publish_at") and row.get("publish_at"):
                parsed["publish_at"] = row.get("publish_at")
            if not parsed.get("publish_ts") and row.get("publish_ts"):
                parsed["publish_ts"] = row.get("publish_ts")
            if not parsed.get("title") or parsed.get("title") == "(无标题)":
                parsed["title"] = title
            filename = safe_export_filename(
                str(parsed.get("title") or title), ext=ext, index=index
            )
            path = write_article_export(article_dir / filename, parsed, fmt)
            completed += 1
            consecutive_failures = 0
            event = {
                **event_base,
                "status": "ok",
                "path": str(path),
                "retries": used_retries,
            }
            _append_jsonl(state_path, event)
            archive_index.record(identity, status="ok", path=str(path))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            consecutive_failures += 1
            error = describe_exception(exc)
            event = {**event_base, "status": "failed", "error": error}
            _append_jsonl(state_path, event)
            _append_jsonl(failure_path, event)
            archive_index.record(identity, status="failed", error=error)
            if _is_rate_limit_error(exc):
                paused = True
                break
            if consecutive_failures >= max(1, int(cooldown_after_failures)):
                low, high = cooldown_range_s
                low = max(0.0, float(low))
                high = max(low, float(high))
                cooldown_s = random.uniform(low, high)
                if on_progress:
                    on_progress(
                        {
                            "current": index,
                            "total": total,
                            "ok": completed,
                            "failed": failed,
                            "skipped": skipped,
                            "retries": retries,
                            "title": title,
                            "status": "cooldown",
                            "cooldown_s": int(cooldown_s),
                        }
                    )
                time.sleep(cooldown_s)
                consecutive_failures = 0
        if pending_index + 1 < len(pending):
            low = max(0.0, float(sleep_min_s))
            high = max(low, float(sleep_max_s))
            if high:
                time.sleep(random.uniform(low, high))
        if should_cancel and should_cancel():
            cancelled = True
            break

    if pending and not paused and not cancelled:
        # Report progress after the final batch even when there was no callback
        # opportunity between two fast mocked requests.
        if on_progress:
            on_progress(
                {
                    "current": total,
                    "total": total,
                    "ok": completed,
                    "failed": failed,
                    "skipped": skipped,
                    "title": "",
                    "status": "done",
                }
            )

    result = {
        "account": account_name,
        "total": total,
        "ok": completed,
        "failed": failed,
        "skipped": skipped,
        "retries": retries,
        "paused_rate_limit": paused,
        "cancelled": cancelled,
        "out_dir": str(output),
        "manifest": str(manifest_path),
        "state": str(state_path),
        "index": str(archive_index.path),
        "max_workers": worker_count,
    }
    (output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
