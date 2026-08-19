from app.history_cache import HistoryCache, make_query_key
from app.unattended_queue import (
    is_rate_limit_listing_error,
    listing_already_complete,
    select_awaiting_accounts,
)


def test_select_awaiting_skips_complete_and_missing_url(tmp_path) -> None:
    cache = HistoryCache(tmp_path / "h.sqlite")
    cache.save_batch(
        make_query_key("done", days=None, date_range=None),
        account_id="done",
        account_name="已完成",
        days=None,
        date_range=None,
        articles=[{"identity": "a", "title": "t", "link": "https://mp.weixin.qq.com/s/a"}],
        next_offset=0,
        complete=True,
    )
    rows = [
        {"id": "done", "status": "awaiting", "article_url": "https://mp.weixin.qq.com/s/a"},
        {"id": "wait", "status": "awaiting", "article_url": "https://mp.weixin.qq.com/s/b"},
        {"id": "nourl", "status": "awaiting", "article_url": ""},
        {"id": "active", "status": "active", "article_url": "https://mp.weixin.qq.com/s/c"},
    ]
    picked = select_awaiting_accounts(rows, cache, days=None, date_range=None)
    assert [r["id"] for r in picked] == ["wait"]
    assert listing_already_complete(cache, "done", days=None, date_range=None) is True


def test_rate_limit_error_detection() -> None:
    assert is_rate_limit_listing_error("ret=-6 unknownerror")
    assert is_rate_limit_listing_error("HTTP 429")
    assert is_rate_limit_listing_error("访问过于频繁")
    assert not is_rate_limit_listing_error("凭证窗口即将结束，列表已缓存")
