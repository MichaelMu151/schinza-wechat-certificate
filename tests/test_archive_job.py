import json
from pathlib import Path

import requests

from app.archive_job import run_archive_job


def _articles() -> list[dict]:
    return [
        {
            "title": "文章一",
            "link": "https://mp.weixin.qq.com/s?a=1&mid=1&idx=1&sn=a",
            "identity": "mid:1|idx:1|sn:a",
            "publish_ts": 1,
            "publish_at": "2026-01-01 00:00",
        },
        {
            "title": "文章二",
            "link": "https://mp.weixin.qq.com/s?a=1&mid=2&idx=1&sn=b",
            "identity": "mid:2|idx:1|sn:b",
            "publish_ts": 2,
            "publish_at": "2026-01-02 00:00",
        },
    ]


def test_archive_writes_manifest_and_resumes(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(url: str, **_kwargs):
        calls.append(url)
        return {
            "title": "正文",
            "source_url": url,
            "content_text": "内容",
            "content_markdown": "内容",
        }

    first = run_archive_job(
        _articles(),
        account_name="测试医院",
        out_dir=tmp_path,
        fetch_article=fetch,
        sleep_min_s=0,
        sleep_max_s=0,
        max_workers=1,
    )
    assert first["ok"] == 2
    assert len(calls) == 2
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "manifest.jsonl").exists()
    assert (tmp_path / "archive_index.sqlite").exists()
    assert len(list((tmp_path / "articles").glob("*.md"))) == 2

    calls.clear()
    second = run_archive_job(
        _articles(),
        account_name="测试医院",
        out_dir=tmp_path,
        fetch_article=fetch,
        sleep_min_s=0,
        sleep_max_s=0,
        max_workers=1,
    )
    assert second["ok"] == 0
    assert second["skipped"] == 2
    assert calls == []
    events = [
        json.loads(line)
        for line in (tmp_path / "job_state.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(event["status"] == "ok" for event in events)


def test_archive_pauses_immediately_on_rate_limit(tmp_path: Path) -> None:
    response = requests.Response()
    response.status_code = 429

    def fetch(_url: str, **_kwargs):
        raise requests.HTTPError("429", response=response)

    result = run_archive_job(
        _articles(),
        account_name="测试医院",
        out_dir=tmp_path,
        fetch_article=fetch,
        sleep_min_s=0,
        sleep_max_s=0,
        max_workers=1,
    )
    assert result["paused_rate_limit"] is True
    assert result["failed"] == 1
    failures = (tmp_path / "failures.jsonl").read_text(encoding="utf-8")
    assert "429" in failures
