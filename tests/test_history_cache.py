from pathlib import Path

from app.history_cache import HistoryCache, make_query_key


def test_history_cache_persists_articles_and_checkpoint(tmp_path: Path) -> None:
    cache = HistoryCache(tmp_path / "history.sqlite")
    key = make_query_key("account-1", days=None, date_range=None)
    cache.save_batch(
        key,
        account_id="account-1",
        account_name="测试医院",
        days=None,
        date_range=None,
        articles=[
            {
                "identity": "mid:1|idx:1|sn:a",
                "title": "旧文章",
                "publish_ts": 1,
                "link": "https://mp.weixin.qq.com/s/a",
            }
        ],
        next_offset=100,
        complete=False,
    )

    reopened = HistoryCache(tmp_path / "history.sqlite")
    loaded = reopened.load(key)
    assert loaded["next_offset"] == 100
    assert loaded["complete"] is False
    assert [article["title"] for article in loaded["articles"]] == ["旧文章"]

    reopened.save_batch(
        key,
        account_id="account-1",
        account_name="测试医院",
        days=None,
        date_range=None,
        articles=[
            {
                "identity": "mid:2|idx:1|sn:b",
                "title": "更旧文章",
                "publish_ts": 0,
                "link": "https://mp.weixin.qq.com/s/b",
            }
        ],
        next_offset=0,
        complete=True,
    )
    final = reopened.load(key)
    assert final["complete"] is True
    assert len(final["articles"]) == 2
