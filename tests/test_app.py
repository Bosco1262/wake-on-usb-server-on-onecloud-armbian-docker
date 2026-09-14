"""Routes, authentication, CSRF and the degradation paths.

路由、鉴权、CSRF 与降级路径。
"""

import os
import subprocess
import sys

import pytest

import app as appmod
from helpers import read_device
from helpers import blank_device as blank

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_index_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_api_requires_login(client):
    assert client.get("/api/status").status_code == 302
    assert client.post("/api/wake", json={"key": "enter"}).status_code == 302


def test_login_page_has_csrf(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'name="_csrf"' in response.data


def test_wrong_password_rejected(client, login_helper):
    response = login_helper(client, password="wrong")
    assert response.status_code == 200
    assert b"Wrong username or password" in response.data


def test_post_without_csrf_is_rejected(client):
    response = client.post("/login", data={"username": "admin", "password": "hunter2"})
    assert response.status_code == 400


def test_login_then_index(auth_client, device_path):
    response = auth_client.get("/")
    assert response.status_code == 200
    body = response.data.decode()
    assert device_path in body
    assert "Wake target device" in body
    assert "USB link state" in body
    assert "<dt>" not in body and "<dd>" not in body


def test_status_endpoint(auth_client, device_path):
    payload = auth_client.get("/api/status").get_json()
    assert payload["ready"] is True
    assert payload["device"] == device_path
    assert payload["lang"] == "en"


def test_wake_form_writes_reports_and_flashes_once(auth_client, csrf, device_path):
    blank(device_path)
    response = auth_client.post(
        "/wake",
        data={"mode": "key", "key": "enter", "repeat": "1", "_csrf": csrf},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Sent:" in response.data.decode()
    assert len(read_device(device_path)) == 16
    assert "Sent:" not in auth_client.get("/").data.decode()


def test_api_wake_json(auth_client, csrf, api, device_path):
    blank(device_path)
    response = api(auth_client, csrf, {"mode": "key", "key": "ctrl+enter", "repeat": 2})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["steps"] == ["key ctrl+enter ×2"]
    assert payload["warnings"] == []
    assert payload["lang"] == "en"
    assert len(read_device(device_path)) == 32


def test_logout(auth_client, csrf):
    assert auth_client.post("/logout", data={"_csrf": csrf}).status_code == 302
    assert auth_client.get("/").status_code == 302


def test_missing_device_degrades_to_503(tmp_path, auth_client, csrf, api, monkeypatch):
    monkeypatch.setattr(appmod, "HID_DEVICE", str(tmp_path / "gone"))
    response = api(auth_client, csrf, {"mode": "key", "key": "enter"})
    assert response.status_code == 503
    assert "does not exist" in response.get_json()["error"]


def test_oversized_body_is_rejected(auth_client, csrf):
    """An unbounded body is a memory-exhaustion vector; 64 KiB is plenty here.

    请求体不设上限会让内存被撑爆，而本项目 64 KiB 已经绰绰有余。
    """
    limit = appmod.app.config["MAX_CONTENT_LENGTH"]
    assert limit, "必须设置 MAX_CONTENT_LENGTH"
    response = auth_client.post(
        "/wake",
        data={"mode": "key", "key": "enter", "repeat": "1", "_csrf": csrf,
              "padding": "x" * (limit + 100)},
    )
    assert response.status_code == 413


# ---------- 登录限流与时序 ----------

def test_login_failure_window_decays(monkeypatch):
    source = "10.99.0.1"
    appmod._clear_login_failures(source)
    now = [1000.0]
    monkeypatch.setattr(appmod.time, "time", lambda: now[0])

    for _ in range(appmod.FAILED_LOGIN_LIMIT):
        appmod._record_login_failure(source)
    assert appmod._login_throttled(source) is True
    assert appmod._login_throttled("10.99.0.2") is False, "限流必须按来源隔离"

    now[0] += appmod.FAILED_LOGIN_WINDOW + 1
    assert appmod._login_throttled(source) is False, "时间窗过后应自动解除"
    appmod._clear_login_failures(source)


def test_successful_login_clears_failures():
    source = "10.99.0.3"
    appmod._clear_login_failures(source)
    for _ in range(appmod.FAILED_LOGIN_LIMIT):
        appmod._record_login_failure(source)
    appmod._clear_login_failures(source)
    assert appmod._login_throttled(source) is False


def test_unknown_username_still_hashes_the_password(monkeypatch):
    """Skipping the hash on a bad username leaks which accounts exist via timing.

    用户名错误时跳过哈希校验，会通过响应时间泄露用户名是否存在。
    """
    calls = []
    real = appmod.check_password_hash

    def spy(stored, candidate):
        calls.append(stored)
        return real(stored, candidate)

    monkeypatch.setattr(appmod, "check_password_hash", spy)
    assert appmod._verify_credentials("nobody", "whatever") is False
    assert calls, "用户名错误时也必须执行一次哈希校验"


def test_known_username_and_password(monkeypatch):
    assert appmod._verify_credentials("admin", "hunter2") is True
    assert appmod._verify_credentials("admin", "wrong") is False


# ---------- 启动期环境变量校验 ----------

@pytest.mark.parametrize("env,name", [
    ({"KEY_HOLD_MS": "abc"}, "KEY_HOLD_MS"),
    ({"KEY_HOLD_MS": "-5"}, "KEY_HOLD_MS"),
    ({"KEY_HOLD_MS": "99999"}, "KEY_HOLD_MS"),
    ({"WAKE_REPEAT": "0"}, "WAKE_REPEAT"),
    ({"WAKE_REPEAT": "9"}, "WAKE_REPEAT"),
    ({"WAKE_MODE": "bogus"}, "WAKE_MODE"),
    ({"WAKE_KEY": "nope"}, "WAKE_KEY"),
])
def test_startup_rejects_bad_env(env, name):
    """A typo in .env must fail loudly at startup, not as a bare traceback.

    .env 里写错必须启动即报明确的错，而不是抛一个裸堆栈。
    """
    proc = subprocess.run(
        [sys.executable, "-c", "import app"],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    assert proc.returncode != 0
    assert "RuntimeError" in proc.stderr
    assert name in proc.stderr


def test_startup_accepts_valid_env():
    proc = subprocess.run(
        [sys.executable, "-c", "import app"],
        env={**os.environ, "KEY_HOLD_MS": "80", "WAKE_REPEAT": "2"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
