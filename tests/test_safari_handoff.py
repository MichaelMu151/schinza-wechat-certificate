from app.safari_handoff import CLICK_NAME_JS, _as_literal, handoff_article_to_wechat


class FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_as_literal_quotes_javascript() -> None:
    text = _as_literal(CLICK_NAME_JS)
    assert text.startswith('"')
    assert "js_name" in text


def test_handoff_clicks_name_then_go(monkeypatch) -> None:
    calls: list[list[str]] = []
    js_returns = iter(
        [
            FakeProc(stdout="complete|https://mp.weixin.qq.com/s/abc"),
            FakeProc(stdout="clicked-js_name"),
            FakeProc(stdout="clicked-go"),
        ]
    )

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["open", "-a"]:
            return FakeProc()
        if cmd[:1] == ["osascript"]:
            return next(js_returns)
        raise AssertionError(cmd)

    monkeypatch.setattr("sys.platform", "darwin")
    result = handoff_article_to_wechat(
        "https://mp.weixin.qq.com/s/abc",
        run=run,
        sleep=lambda _s: None,
    )
    assert result["name"] == "clicked-js_name"
    assert result["go_js"] == "clicked-go"
    assert any(c[:3] == ["open", "-a", "Safari"] for c in calls)
