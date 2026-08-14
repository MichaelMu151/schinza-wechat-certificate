from pathlib import Path

from app.history_cache import HistoryCache, make_query_key
from app.history_pipeline import run_list_and_archive


def test_pipeline_auto_continues_pages_then_archives(tmp_path: Path) -> None:
    cache = HistoryCache(tmp_path / "history.sqlite")
    calls: list[int] = []
    archived: list[str] = []

    def fetch(_cred, *, start_offset=0, **_kwargs):
        calls.append(start_offset)
        if start_offset == 0:
            return {
                "ok": True,
                "articles": [
                    {
                        "identity": "mid:1|idx:1|sn:a",
                        "title": "一",
                        "link": "https://mp.weixin.qq.com/s/a",
                        "publish_ts": 2,
                    }
                ],
                "pages": 100,
                "hit_page_cap": True,
                "pagination_stalled": False,
                "next_offset": 100,
                "cancelled": False,
            }
        return {
            "ok": True,
            "articles": [
                {
                    "identity": "mid:2|idx:1|sn:b",
                    "title": "二",
                    "link": "https://mp.weixin.qq.com/s/b",
                    "publish_ts": 1,
                }
            ],
            "pages": 1,
            "hit_page_cap": False,
            "pagination_stalled": False,
            "next_offset": 110,
            "cancelled": False,
        }

    def archive(articles, **_kwargs):
        archived.extend(str(a["title"]) for a in articles)
        return {"ok": len(articles), "failed": 0, "skipped": 0, "cancelled": False}

    result = run_list_and_archive(
        {"__biz": "biz", "uin": "u", "key": "k"},
        account_id="acc-1",
        account_name="测试医院",
        cache=cache,
        days=None,
        date_range=None,
        start_ts=None,
        end_ts=None,
        sightings=[],
        out_dir=tmp_path / "out",
        fetch_history=fetch,
        archive=archive,
        batch_pause_s=0,
    )
    assert calls == [0, 100]
    assert result["listing_complete"] is True
    assert result["articles"] == 2
    assert archived == ["一", "二"]
    assert result["archive"]["ok"] == 2


def test_pipeline_continues_when_can_continue_false_via_fetch_contract(
    tmp_path: Path, monkeypatch
) -> None:
    """The pipeline must not depend on can_msg_continue; advancing offset is enough."""
    from app import history_client

    cache = HistoryCache(tmp_path / "history.sqlite")
    calls: list[int] = []

    def page(_cred, *, offset, **_kwargs):
        calls.append(offset)
        return {
            "ok": True,
            "articles": [
                {
                    "title": f"文章{offset}",
                    "link": f"https://mp.weixin.qq.com/s/{offset}",
                    "publish_ts": 1704067200,
                    "identity": f"mid:{offset}|idx:1|sn:x",
                }
            ],
            "can_continue": False,
            "next_offset": offset + 10 if offset == 0 else offset,
            "raw": {"general_msg_list": {"list": [{}]}},
        }

    monkeypatch.setattr(history_client, "fetch_getmsg_page", page)
    monkeypatch.setattr(history_client.time, "sleep", lambda *_a, **_k: None)
    result = run_list_and_archive(
        {"__biz": "biz", "uin": "u", "key": "k"},
        account_id="acc-1",
        account_name="测试医院",
        cache=cache,
        days=None,
        date_range=None,
        start_ts=None,
        end_ts=None,
        sightings=[],
        out_dir=tmp_path / "out",
        archive=lambda articles, **_k: {
            "ok": len(articles),
            "failed": 0,
            "skipped": 0,
            "cancelled": False,
        },
        batch_pause_s=0,
        max_pages_per_batch=10,
    )
    assert calls == [0, 10]
    assert result["articles"] == 2
    assert result["listing_complete"] is True
    assert result["archive"]["ok"] == 2


def test_pipeline_skips_listing_and_archives_cache(tmp_path: Path) -> None:
    cache = HistoryCache(tmp_path / "history.sqlite")
    key = make_query_key("acc-1", days=None, date_range=None)
    cache.save_batch(
        key,
        account_id="acc-1",
        account_name="测试医院",
        days=None,
        date_range=None,
        articles=[
            {
                "identity": "mid:1|idx:1|sn:a",
                "title": "缓存文",
                "link": "https://mp.weixin.qq.com/s/a",
                "publish_ts": 1,
            }
        ],
        next_offset=10,
        complete=False,
    )
    fetch_calls: list[int] = []
    seen_cred: list[object] = []

    def archive(articles, **kwargs):
        seen_cred.append(kwargs.get("cred", "missing"))
        return {"ok": len(articles), "failed": 0, "skipped": 0, "cancelled": False}

    result = run_list_and_archive(
        {"__biz": "biz", "uin": "u", "key": "k"},
        account_id="acc-1",
        account_name="测试医院",
        cache=cache,
        days=None,
        date_range=None,
        start_ts=None,
        end_ts=None,
        sightings=[],
        out_dir=tmp_path / "out",
        skip_listing=True,
        fetch_history=lambda *_a, **_k: fetch_calls.append(1) or {"ok": True, "articles": []},
        archive=archive,
    )
    assert fetch_calls == []
    assert result["articles"] == 1
    assert result["archive"]["ok"] == 1
    assert seen_cred == [None]


def test_pipeline_stops_listing_when_credential_deadline_passes(tmp_path: Path) -> None:
    cache = HistoryCache(tmp_path / "history.sqlite")
    fetches = 0

    def fetch(_cred, **_kwargs):
        nonlocal fetches
        fetches += 1
        return {
            "ok": True,
            "articles": [
                {
                    "identity": "mid:1|idx:1|sn:a",
                    "title": "一",
                    "link": "https://mp.weixin.qq.com/s/a",
                    "publish_ts": 1,
                }
            ],
            "pages": 1,
            "hit_page_cap": True,
            "next_offset": 10,
            "cancelled": False,
        }

    result = run_list_and_archive(
        {"__biz": "biz", "uin": "u", "key": "k"},
        account_id="acc-1",
        account_name="测试医院",
        cache=cache,
        days=None,
        date_range=None,
        start_ts=None,
        end_ts=None,
        sightings=[],
        out_dir=tmp_path / "out",
        cred_deadline_ts=0,
        fetch_history=fetch,
        archive=lambda articles, **_k: {
            "ok": len(articles),
            "failed": 0,
            "skipped": 0,
            "cancelled": False,
        },
        batch_pause_s=0,
    )
    assert fetches == 0
    assert result["listing_error"]
    assert "凭证窗口" in result["listing_error"]
    assert result["archive"] is None


def test_pipeline_defers_bodies_when_list_incomplete_after_deadline(
    tmp_path: Path,
) -> None:
    cache = HistoryCache(tmp_path / "history.sqlite")
    clock = {"t": 0.0}
    fetches = 0
    archive_calls = 0

    def now() -> float:
        return clock["t"]

    def fetch(_cred, **_kwargs):
        nonlocal fetches
        fetches += 1
        clock["t"] = 100.0
        return {
            "ok": True,
            "articles": [
                {
                    "identity": "mid:1|idx:1|sn:a",
                    "title": "一",
                    "link": "https://mp.weixin.qq.com/s/a",
                    "publish_ts": 1,
                }
            ],
            "pages": 1,
            "hit_page_cap": True,
            "next_offset": 10,
            "cancelled": False,
        }

    def archive(articles, **_k):
        nonlocal archive_calls
        archive_calls += 1
        return {"ok": len(articles), "failed": 0, "skipped": 0, "cancelled": False}

    result = run_list_and_archive(
        {"__biz": "biz", "uin": "u", "key": "k"},
        account_id="acc-1",
        account_name="测试医院",
        cache=cache,
        days=None,
        date_range=None,
        start_ts=None,
        end_ts=None,
        sightings=[],
        out_dir=tmp_path / "out",
        cred_deadline_ts=50,
        time_fn=now,
        fetch_history=fetch,
        archive=archive,
        batch_pause_s=0,
    )
    assert fetches == 1
    assert archive_calls == 0
    assert result["articles"] == 1
    assert result["listing_complete"] is False
    assert result["archive"] is None
    assert "凭证窗口" in (result["listing_error"] or "")
