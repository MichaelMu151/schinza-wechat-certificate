from app.safari_handoff import (
    CLICK_NAME_JS,
    _as_literal,
    handoff_article_to_wechat,
    probe_macos_automation,
)


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

    def run(cmd, **kwargs):
        calls.append(cmd)
        stdin = kwargs.get("input") or ""
        if cmd[:2] == ["open", "-a"]:
            return FakeProc()
        if cmd[:1] == ["osascript"]:
            if "readyState" in stdin:
                return FakeProc(
                    stdout="complete|https://mp.weixin.qq.com/s/abc|has-name"
                )
            if "clicked-js_name" in stdin:
                return FakeProc(stdout="clicked-js_name")
            if "前往" in stdin and "do JavaScript" in stdin:
                return FakeProc(stdout="clicked-go")
            return FakeProc(stdout="ok")
        raise AssertionError(cmd)

    monkeypatch.setattr("sys.platform", "darwin")
    result = handoff_article_to_wechat(
        "https://mp.weixin.qq.com/s/abc",
        run=run,
        sleep=lambda _s: None,
    )
    assert result["name"] == "clicked-js_name"
    assert result["go_js"] == "clicked-go"
    assert "has-name" in result["ready"]
    assert any(c[:3] == ["open", "-a", "Safari"] for c in calls)
    assert any(c[:1] == ["osascript"] for c in calls)


def test_probe_reports_accessibility_failure(monkeypatch) -> None:
    def run(cmd, **kwargs):
        stdin = kwargs.get("input") or ""
        if "System Events" in stdin:
            return FakeProc(returncode=1, stderr="not allowed")
        if "do JavaScript" in stdin:
            return FakeProc(stdout="true")
        return FakeProc(stdout="Safari")

    monkeypatch.setattr("sys.platform", "darwin")
    issues = probe_macos_automation(run=run)
    assert any("辅助功能" in item for item in issues)
    assert not any("JavaScript" in item for item in issues)
