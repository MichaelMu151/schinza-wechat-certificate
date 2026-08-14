from app import history_client


def test_history_starts_from_checkpoint_and_reports_next_offset(monkeypatch) -> None:
    calls: list[int] = []

    def page(_cred, *, offset, **_kwargs):
        calls.append(offset)
        return {
            "ok": True,
            "articles": [
                {
                    "title": "文章",
                    "link": "https://mp.weixin.qq.com/s/x",
                    "publish_ts": 1704067200,
                }
            ],
            "can_continue": True,
            "next_offset": offset + 10,
            "raw": {"general_msg_list": {"list": [{}]}},
        }

    monkeypatch.setattr(history_client, "fetch_getmsg_page", page)
    result = history_client.fetch_history_days(
        {"__biz": "biz", "uin": "uin", "key": "key"},
        days=None,
        max_pages=1,
        sleep_s=0,
        start_offset=100,
    )
    assert calls == [100]
    assert result["start_offset"] == 100
    assert result["next_offset"] == 110
    assert result["hit_page_cap"] is True


def test_history_stops_when_wechat_says_no_more(monkeypatch) -> None:
    def page(_cred, *, offset, **_kwargs):
        return {
            "ok": True,
            "articles": [
                {
                    "title": "最后一篇",
                    "link": "https://mp.weixin.qq.com/s/x",
                    "publish_ts": 1704067200,
                }
            ],
            "can_continue": False,
            "next_offset": offset + 10,
            "raw": {"general_msg_list": {"list": [{}]}},
        }

    monkeypatch.setattr(history_client, "fetch_getmsg_page", page)
    result = history_client.fetch_history_days(
        {"__biz": "biz", "uin": "uin", "key": "key"},
        days=None,
        max_pages=1,
        sleep_s=0,
    )
    assert result["hit_page_cap"] is False
