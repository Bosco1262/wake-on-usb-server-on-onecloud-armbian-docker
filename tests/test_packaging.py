"""Check that the packaging wires up what the app needs and nothing more.

These are text-level assertions on purpose: pulling in a YAML parser for four
checks is not worth the dependency.

对打包配置做文本层面的检查：为了四条断言引入 YAML 解析依赖并不划算。
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


@pytest.mark.parametrize("asset", [
    "app.py", "hid.py", "i18n.py", "templates", "static", "locales",
])
def test_runtime_assets_are_copied_into_the_image(asset):
    assert asset in DOCKERFILE, "%s 没有被复制进镜像" % asset


def test_image_does_not_carry_tests_or_secrets():
    for entry in ("tests", "requirements-dev.txt", ".env"):
        assert entry in DOCKERIGNORE, "%s 应当被 .dockerignore 排除" % entry


def test_container_gets_the_hid_device():
    assert "/dev/hidg0:/dev/hidg0" in COMPOSE


def test_container_is_not_privileged():
    assert "privileged" not in COMPOSE


def test_compose_reads_the_env_file():
    assert "env_file: .env" in COMPOSE


def test_single_worker_with_threads():
    """Multiple processes would break the in-process write lock in hid.py.

    多进程会让 hid.py 里的进程内写锁失效。
    """
    assert '"-w", "1"' in DOCKERFILE
    assert '"--threads"' in DOCKERFILE


def test_env_example_documents_every_knob():
    for name in ("SECRET_KEY", "APP_USER", "APP_PASSWORD", "APP_LANG", "COOKIE_SECURE",
                 "WAKE_MODE", "WAKE_KEY", "WAKE_REPEAT", "KEY_HOLD_MS",
                 "HID_DEVICE", "GADGET_NAME", "ENABLE_UDC_REBIND"):
        assert name in ENV_EXAMPLE, ".env.example 里缺少 %s" % name


def test_dev_requirements_pin_pytest():
    assert (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").strip().startswith("pytest")
