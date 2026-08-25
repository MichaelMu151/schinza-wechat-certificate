from app.mitm_addon import _merge_from_urlencoded
from app.mitm_capture import MACOS_WECHAT_LOCAL_SPEC, capture_proxy_modes


def test_parse_redirector_waiting_for_user() -> None:
    from app.macos_intercept import parse_redirector_state

    text = (
        "enabled\tactive\tteamID\tbundleID (version)\tname\t[state]\n"
        "\t*\tS8XHQB96PW\torg.mitmproxy.macos-redirector.network-extension "
        "(2.0/1)\tnetwork-extension\t[activated waiting for user]\n"
    )
    assert parse_redirector_state(text) == "waiting_for_user"
    enabled = text.replace("waiting for user", "enabled")
    assert parse_redirector_state(enabled) == "enabled"
    assert parse_redirector_state("no extension here") == "missing"


def test_macos_capture_modes_include_wechat_local_redirect() -> None:
    modes = capture_proxy_modes(platform="darwin", use_local=True)
    assert modes[0] == "regular"
    assert modes[1] == f"local:{MACOS_WECHAT_LOCAL_SPEC}"
    assert "WeChatAppEx Helper" in MACOS_WECHAT_LOCAL_SPEC


def test_macos_can_fall_back_to_regular_only() -> None:
    assert capture_proxy_modes(platform="darwin", use_local=False) == ["regular"]
    assert capture_proxy_modes(platform="win32", use_local=True) == ["regular"]


def test_merge_credentials_from_post_body() -> None:
    bucket: dict[str, str] = {}
    changed = _merge_from_urlencoded(
        "__biz=MzA5OTM4MzM2MA==&uin=123&key=abc&pass_ticket=pt",
        bucket,
    )
    assert changed is True
    assert bucket["__biz"] == "MzA5OTM4MzM2MA=="
    assert bucket["uin"] == "123"
    assert bucket["key"] == "abc"
    assert _merge_from_urlencoded('{"__biz":"no"}', bucket) is False
