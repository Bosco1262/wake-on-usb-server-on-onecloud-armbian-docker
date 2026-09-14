"""Shared fixtures: environment, a stand-in HID device and logged-in clients.

The environment must be in place before app/i18n are imported, so it is set at
module import time here (conftest is imported before the test modules).

共享夹具：环境变量、替代 /dev/hidg0 的普通文件、以及已登录的客户端。

环境必须在导入 app/i18n 之前就绪，因此在这里（conftest 早于测试模块导入）
于模块导入期设置。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="hidwake-tests-"))
FAKE_HID = _TMP / "hidg0"
FAKE_HID.write_bytes(b"")

os.environ.update(
    SECRET_KEY="test-secret-key",
    APP_USER="admin",
    APP_PASSWORD="hunter2",
    HID_DEVICE=str(FAKE_HID),
)

# Windows has no os.O_NONBLOCK; the target platform always does.
#
# Windows 上没有 os.O_NONBLOCK，目标平台一定有。
if not hasattr(os, "O_NONBLOCK"):
    os.O_NONBLOCK = 0

import app as appmod  # noqa: E402
import hid  # noqa: E402
import i18n  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: takes over a second")


@pytest.fixture()
def device_path():
    return str(FAKE_HID)


@pytest.fixture()
def blank_device(device_path):
    """Empty the stand-in device so one test's reports cannot leak into the next.

    清空替代设备，避免上一个用例写下的报文影响下一个。
    """
    Path(device_path).write_bytes(b"")
    return device_path


@pytest.fixture()
def client():
    appmod.app.config.update(TESTING=True)
    return appmod.app.test_client()


def login(client, headers=None, password="hunter2"):
    """Log in and return the response. Re-reads the CSRF token as needed.

    登录并返回响应。CSRF token 会按需重新获取。
    """
    headers = headers or {}
    client.get("/login", headers=headers)
    with client.session_transaction() as sess:
        token = sess["_csrf"]
    return client.post(
        "/login",
        data={"username": "admin", "password": password, "_csrf": token},
        headers=headers,
    )


@pytest.fixture()
def login_helper():
    return login


@pytest.fixture()
def auth_client(client):
    login(client)
    client.get("/")  # 登录会清空会话，重新渲染以重建 CSRF token
    return client


@pytest.fixture()
def csrf(auth_client):
    with auth_client.session_transaction() as sess:
        return sess["_csrf"]


@pytest.fixture()
def api():
    """POST to /api/wake with a valid CSRF token.

    Pass `json_body` for a normal object, or `raw` to send a hand-written body
    (needed to exercise malformed JSON).

    带合法 CSRF token 向 /api/wake 发送请求。普通对象用 `json_body`，需要构造
    畸形 JSON 时用 `raw` 直接给原始请求体。
    """
    def _post(client, token, json_body=None, raw=None, **kwargs):
        headers = {"X-CSRF-Token": token}
        headers.update(kwargs.pop("headers", {}))
        if raw is not None:
            return client.post("/api/wake", data=raw, content_type="application/json",
                               headers=headers, **kwargs)
        return client.post("/api/wake", json=json_body, headers=headers, **kwargs)

    return _post
