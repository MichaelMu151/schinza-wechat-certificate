from app.safari_handoff import (
    CLICK_NAME_JS,
    DEFAULT_GO_BUTTON_POINT,
    _as_literal,
    handoff_article_to_wechat,
    parse_go_button_point,
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


def test_parse_go_button_point_defaults_and_env() -> None:
    assert DEFAULT_GO_BUTTON_POINT == (958, 640)
    assert parse_go_button_point("") == (958, 640)
    assert parse_go_button_point("1200, 800") == (1200, 800)
    assert parse_go_button_point("bad") == (958, 640)


def test_handoff_clicks_fullscreen_go_coordinates(monkeypatch) -> None:
    inputs: list[str] = []

    def run(cmd, **kwargs):
        stdin = kwargs.get("input") or ""
        inputs.append(stdin)
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
            if "whose frontmost" in stdin:
                return FakeProc(stdout="Safari")
            if 'return "has-sheet"' in stdin:
                return FakeProc(stdout="no-sheet")
            if "958" in stdin and "640" in stdin:
                return FakeProc(stdout="xy:958,640")
            return FakeProc(stdout="ok")
        raise AssertionError(cmd)

    monkeypatch.setattr("sys.platform", "darwin")
    result = handoff_article_to_wechat(
        "https://mp.weixin.qq.com/s/abc",
        run=run,
        sleep=lambda _s: None,
    )
    assert result["name"] == "clicked-js_name"
    assert result["go_xy"] == "xy:958,640"
    assert DEFAULT_GO_BUTTON_POINT == (958, 640)
    assert any("click at {958, 640}" in text for text in inputs)


def test_handoff_clicks_safari_system_sheet(monkeypatch) -> None:
    def run(cmd, **kwargs):
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
            if "whose frontmost" in stdin:
                return FakeProc(stdout="Safari")
            if 'return "has-sheet"' in stdin:
                return FakeProc(stdout="has-sheet")
            if "click button 2" in stdin:
                return FakeProc(stdout="ax-sheet-btn2:Safari")
            if "958" in stdin and "640" in stdin:
                return FakeProc(stdout="xy:958,640")
            return FakeProc(stdout="ok")
        raise AssertionError(cmd)

    monkeypatch.setattr("sys.platform", "darwin")
    result = handoff_article_to_wechat(
        "https://mp.weixin.qq.com/s/abc",
        run=run,
        sleep=lambda _s: None,
    )
    assert result["name"] == "clicked-js_name"
    assert result["go_xy"] == "xy:958,640"
    assert result["go_ax"].startswith("ax-sheet-btn2")


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
