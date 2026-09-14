"""Regression tests for the malformed-input holes found in review.

Every test here failed before the corresponding fix.

评审中发现的一批畸形输入问题，逐条固定为回归用例。

这里的每个用例在修复前都是失败的。
"""

import pytest

from helpers import random_key, read_device, set_cookie_sizes
from helpers import blank_device as blank


# ---------- 请求体形态 ----------

@pytest.mark.parametrize("raw", ["[1,2,3]", '"a string"', "42", "true", "null", "", "{bad json"])
def test_non_object_or_malformed_json_body_is_rejected(auth_client, csrf, api, raw):
    """Anything but a JSON object used to blow up with a 500.

    只要不是 JSON 对象，修复前会直接 500。
    """
    response = api(auth_client, csrf, raw=raw)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_malformed_json_does_not_fire_a_wake(auth_client, csrf, api, device_path):
    """A request whose meaning is unclear must not perform a physical action.

    语义不明的请求不应真的触发一次物理动作。
    """
    blank(device_path)
    assert api(auth_client, csrf, raw="{bad json").status_code == 400
    assert read_device(device_path) == b""


@pytest.mark.parametrize("payload,status", [
    ({"mode": 123, "key": "enter"}, 400),
    ({"mode": ["key"], "key": "enter"}, 400),
    ({"mode": True, "key": "enter"}, 400),
    ({"mode": "key", "key": 123}, 400),
    ({"mode": "key", "key": ["a"]}, 400),
    ({"mode": "key", "key": {}}, 400),
    ({"mode": "key", "key": None}, 200),
    ({"mode": None, "key": None}, 200),
])
def test_mode_and_key_must_be_strings(auth_client, csrf, api, device_path, payload, status):
    blank(device_path)
    assert api(auth_client, csrf, payload).status_code == status


# ---------- 长度限制 ----------

@pytest.mark.parametrize("key", [
    "x" * 33,
    "a" * 200,
    "ctrl+" + "a" * 100,
])
def test_over_long_key_is_rejected(auth_client, csrf, api, key):
    assert api(auth_client, csrf, {"mode": "key", "key": key}).status_code == 400


def test_over_long_mode_is_rejected(auth_client, csrf, api):
    assert api(auth_client, csrf, {"mode": "m" * 200, "key": "enter"}).status_code == 400


@pytest.mark.parametrize("length,needle", [(32, "Unknown key"), (33, "Invalid key parameter")])
def test_key_length_boundary(auth_client, csrf, api, length, needle):
    """32 characters is the limit; both sides of it are pinned.

    按键上限为 32 字符，边界两侧都要固定住。
    """
    response = api(auth_client, csrf, {"mode": "key", "key": "a" * length})
    assert response.status_code == 400
    assert needle in response.get_json()["error"]


def test_long_key_cannot_bloat_the_session_cookie(auth_client, csrf):
    """A 4000-char key used to push the signed session cookie past 4096 bytes,
    which makes the browser drop it and silently logs the user out.

    4000 字符的按键曾把签名会话 cookie 顶过 4096 字节上限，浏览器会整条丢弃，
    表现为用户被静默登出。
    """
    response = auth_client.post(
        "/wake",
        data={"mode": "key", "key": random_key(4000), "repeat": "1", "_csrf": csrf},
    )
    assert response.status_code == 302, "表单路由通过重定向交回结果"
    assert max(set_cookie_sizes(response), default=0) < 1024, "超长输入不得进入会话 cookie"
    assert "Invalid key parameter" in auth_client.get("/").data.decode()


# ---------- repeat 的严格解析 ----------

@pytest.mark.parametrize("repeat", [True, False, 0, 6, 999, 1.9, -1, {"a": 1}, [1], "abc"])
def test_invalid_repeat_is_rejected(auth_client, csrf, api, device_path, repeat):
    blank(device_path)
    response = api(auth_client, csrf, {"mode": "key", "key": "enter", "repeat": repeat})
    assert response.status_code == 400
    assert read_device(device_path) == b""


@pytest.mark.parametrize("repeat", [None, ""])
def test_absent_repeat_uses_the_default(auth_client, csrf, api, repeat):
    """An omitted or blank repeat means "use the default", like mode and key.

    省略或留空的重复次数表示「用默认值」，与 mode / key 保持一致。
    """
    assert api(auth_client, csrf, {"mode": "key", "repeat": repeat}).status_code == 200


@pytest.mark.parametrize("repeat", [1, 2, 5, "3"])
def test_valid_repeat_is_accepted(auth_client, csrf, api, device_path, repeat):
    blank(device_path)
    response = api(auth_client, csrf, {"mode": "key", "key": "enter", "repeat": repeat})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_repeat_zero_is_not_silently_treated_as_one(auth_client, csrf, api, device_path):
    """`0 or DEFAULT` used to turn an invalid 0 into a real wake.

    `0 or DEFAULT` 曾把非法的 0 静默变成一次真实唤醒。
    """
    blank(device_path)
    assert api(auth_client, csrf, {"mode": "key", "repeat": 0}).status_code == 400
    assert read_device(device_path) == b""


# ---------- 状态码语义 ----------

def test_unknown_key_is_a_client_error(auth_client, csrf, api):
    """A typo in the key is a 400; only device trouble is a 503.

    按键拼错属于 400，只有设备侧问题才是 503。
    """
    response = api(auth_client, csrf, {"mode": "key", "key": "nosuchkey"})
    assert response.status_code == 400
    assert "Unknown key" in response.get_json()["error"]


def test_unknown_mode_is_a_client_error(auth_client, csrf, api, device_path):
    blank(device_path)
    assert api(auth_client, csrf, {"mode": "bogus"}).status_code == 400
    assert read_device(device_path) == b""


def test_bad_chord_is_a_client_error(auth_client, csrf, api):
    assert api(auth_client, csrf, {"mode": "key", "key": "nope+enter"}).status_code == 400


def test_device_trouble_is_still_a_503(tmp_path, auth_client, csrf, api, monkeypatch):
    import app as appmod

    monkeypatch.setattr(appmod, "HID_DEVICE", str(tmp_path / "gone"))
    assert api(auth_client, csrf, {"mode": "key", "key": "enter"}).status_code == 503


# ---------- lang 参数的类型 ----------

def test_non_string_lang_is_ignored(auth_client, csrf, api, device_path):
    """`{"lang": 123}` used to raise inside normalize() and 500 every route.

    `{"lang": 123}` 曾在 normalize() 里抛异常，任何路由都会 500。
    """
    blank(device_path)
    response = api(auth_client, csrf, {"mode": "key", "key": "enter", "lang": 123})
    assert response.status_code == 200
    assert response.get_json()["lang"] == "en"


@pytest.mark.parametrize("value", [123, 1.5, True, ["en"], {"a": 1}, b"en", object()])
def test_non_string_lang_never_raises_on_the_login_page(client, value):
    """The language hook runs before authentication, so this was reachable
    unauthenticated.

    语言钩子在鉴权之前执行，因此这条路径未登录也能打到。
    """
    import i18n

    assert i18n.normalize(value) is None
    assert client.get("/login", query_string={"lang": value}).status_code in (200, 302)
