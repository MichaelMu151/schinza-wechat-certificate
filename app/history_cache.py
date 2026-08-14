"""Durable SQLite cache for large, multi-session history fetches."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def make_query_key(
    account_id: str,
    *,
    days: int | None,
    date_range: tuple[str, str] | None,
) -> str:
    payload = json.dumps(
        {
            "account_id": account_id,
            "days": days,
            "date_range": list(date_range) if date_range else None,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class HistoryCache:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS history_queries (
                    query_key TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    account_name TEXT,
                    scope_json TEXT NOT NULL,
                    next_offset INTEGER NOT NULL DEFAULT 0,
                    complete INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                );
                CREATE TABLE IF NOT EXISTS history_articles (
                    query_key TEXT NOT NULL,
                    identity TEXT NOT NULL,
                    publish_ts INTEGER,
                    article_json TEXT NOT NULL,
                    PRIMARY KEY (query_key, identity),
                    FOREIGN KEY (query_key) REFERENCES history_queries(query_key)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_history_articles_order
                    ON history_articles(query_key, publish_ts DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _identity(article: dict[str, Any]) -> str:
        return str(
            article.get("identity")
            or article.get("link")
            or f"{article.get('title')}|{article.get('publish_ts')}"
        )

    def load(self, query_key: str) -> dict[str, Any]:
        with self._connect() as conn:
            query = conn.execute(
                "SELECT * FROM history_queries WHERE query_key=?", (query_key,)
            ).fetchone()
            if query is None:
                return {"articles": [], "next_offset": 0, "complete": False}
            rows = conn.execute(
                """
                SELECT article_json FROM history_articles
                WHERE query_key=?
                ORDER BY COALESCE(publish_ts, 0) DESC, identity
                """,
                (query_key,),
            ).fetchall()
        articles = []
        for row in rows:
            try:
                article = json.loads(row["article_json"])
            except json.JSONDecodeError:
                continue
            if isinstance(article, dict):
                articles.append(article)
        return {
            "articles": articles,
            "next_offset": int(query["next_offset"] or 0),
            "complete": bool(query["complete"]),
            "account_name": query["account_name"],
        }

    def save_batch(
        self,
        query_key: str,
        *,
        account_id: str,
        account_name: str,
        days: int | None,
        date_range: tuple[str, str] | None,
        articles: list[dict[str, Any]],
        next_offset: int,
        complete: bool,
    ) -> None:
        scope = json.dumps(
            {"days": days, "date_range": list(date_range) if date_range else None},
            ensure_ascii=False,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO history_queries (
                    query_key, account_id, account_name, scope_json,
                    next_offset, complete, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                ON CONFLICT(query_key) DO UPDATE SET
                    account_name=excluded.account_name,
                    scope_json=excluded.scope_json,
                    next_offset=excluded.next_offset,
                    complete=excluded.complete,
                    updated_at=datetime('now','localtime')
                """,
                (
                    query_key,
                    account_id,
                    account_name,
                    scope,
                    max(0, int(next_offset)),
                    int(bool(complete)),
                ),
            )
            for article in articles:
                identity = self._identity(article)
                if not identity:
                    continue
                conn.execute(
                    """
                    INSERT INTO history_articles (
                        query_key, identity, publish_ts, article_json
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(query_key, identity) DO UPDATE SET
                        publish_ts=excluded.publish_ts,
                        article_json=excluded.article_json
                    """,
                    (
                        query_key,
                        identity,
                        int(article.get("publish_ts") or 0),
                        json.dumps(article, ensure_ascii=False),
                    ),
                )

    def count(self, query_key: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM history_articles WHERE query_key=?",
                (query_key,),
            ).fetchone()
        return int(row["c"] or 0)
