"""HID key parsing, report bytes and the wake-up sequence.

HID 按键解析、报文字节与唤醒流程。
"""

import errno
import os

import pytest

import hid
from helpers import read_device


@pytest.mark.parametrize("spec,expected", [
    ("enter", (0, 0x28)),
    ("esc", (0, 0x29)),
    ("backspace", (0, 0x2A)),
    ("tab", (0, 0x2B)),
    ("space", (0, 0x2C)),
    ("a", (0, 0x04)),
    ("z", (0, 0x1D)),
    ("1", (0, 0x1E)),
    ("9", (0, 0x26)),
    ("0", (0, 0x27)),
    ("f1", (0, 0x3A)),
    ("f4", (0, 0x3D)),
    ("f12", (0, 0x45)),
    ("delete", (0, 0x4C)),
    ("up", (0, 0x52)),
    ("ctrl+enter", (0x01, 0x28)),
    ("shift+a", (0x02, 0x04)),
    ("alt+f4", (0x04, 0x3D)),
    ("ctrl+shift+enter", (0x03, 0x28)),
    ("CTRL+ENTER", (0x01, 0x28)),
    ("  ctrl + enter  ", (0x01, 0x28)),
])
def test_parse_key_valid(spec, expected):
    assert hid.parse_key(spec) == expected


@pytest.mark.parametrize("spec,key", [
    ("", "err.key.empty"),
    ("ctrl+", "err.key.empty"),
    ("ctrl+shift+", "err.key.empty"),
    ("nope", "err.key.unknown"),
    ("ctrl+nope", "err.key.unknown"),
    ("ctrl+shift+nope", "err.key.unknown"),
    ("nope+ctrl", "err.modifier.unknown"),
])
def test_parse_key_invalid(spec, key):
    with pytest.raises(hid.HIDError) as excinfo:
        hid.parse_key(spec)
    assert excinfo.value.key == key


def test_error_carries_key_and_params():
    with pytest.raises(hid.HIDError) as excinfo:
        hid.parse_key("nope")
    assert excinfo.value.key == "err.key.unknown"
    assert excinfo.value.params == {"name": "nope"}
    assert str(excinfo.value) == "err.key.unknown"


def test_client_errors_are_a_distinct_type():
    """Bad key/mode must be reportable as 400, not 503.

    按键/模式非法属于客户端错误，应能报成 400 而不是 503。
    """
    assert issubclass(hid.InvalidInput, hid.HIDError)
    assert not issubclass(hid.BusSuspended, hid.InvalidInput)
    with pytest.raises(hid.InvalidInput):
        hid.parse_key("nope")
    with pytest.raises(hid.InvalidInput):
        hid.wake("bogus", device="unused", key="enter")
    with pytest.raises(hid.InvalidInput):
        hid.press_key("unused", "enter", repeat=99)


def test_press_writes_press_then_release(blank_device):
    assert hid.press_key(blank_device, "enter", hold_ms=1, repeat=1) is None
    assert read_device(blank_device) == bytes([0, 0, 0x28, 0, 0, 0, 0, 0]) + bytes(8)


def test_repeat_writes_full_cycles(blank_device):
    hid.press_key(blank_device, "ctrl+a", hold_ms=1, repeat=2)
    cycle = bytes([0x01, 0, 0x04, 0, 0, 0, 0, 0]) + bytes(8)
    assert read_device(blank_device) == cycle * 2


def test_missing_device_raises(tmp_path):
    with pytest.raises(hid.HIDError) as excinfo:
        hid.wake("key", device=str(tmp_path / "nope"))
    assert excinfo.value.key == "err.device.missing"
    assert excinfo.value.params["device"].endswith("nope")


def test_send_signal_without_kernel_patch(blank_device):
    step, warnings = hid.send_signal(blank_device)
    assert step == "step.zero_report"
    assert warnings == ["warn.no_wakeup_patch"]
    assert read_device(blank_device) == bytes(8)


def test_wake_reports_steps_and_warnings(blank_device):
    result = hid.wake("both", device=blank_device, key="enter", repeat=1, hold_ms=1)
    assert [step["key"] for step in result["steps"]] == ["step.zero_report", "step.key"]
    assert result["steps"][1]["params"] == {"key": "enter", "repeat": 1}
    assert result["warnings"] == ["warn.no_wakeup_patch"]
    assert set(result) == {"mode", "key", "repeat", "steps", "warnings"}


@pytest.fixture()
def block_writes(monkeypatch):
    """Make os.write fail with EAGAIN after `after` successful calls.

    让 os.write 在成功调用 `after` 次之后开始返回 EAGAIN。
    """
    def _install(after=0):
        real = os.write
        state = {"calls": 0}

        def wrapper(fd, data):
            state["calls"] += 1
            if state["calls"] > after:
                raise BlockingIOError(errno.EAGAIN, "try again")
            return real(fd, data)

        monkeypatch.setattr(os, "write", wrapper)

    return _install


def test_blocked_release_is_reported_not_raised(blank_device, block_writes):
    block_writes(after=1)
    assert hid.press_key(blank_device, "enter", hold_ms=1, repeat=1) == "release_blocked"
    assert read_device(blank_device) == bytes([0, 0, 0x28, 0, 0, 0, 0, 0])


def test_all_writes_blocked_reports_press_blocked(blank_device, block_writes):
    block_writes(after=0)
    assert hid.press_key(blank_device, "enter", hold_ms=1) == "press_blocked"


def test_suspended_bus_surfaces_as_a_warning(blank_device, block_writes):
    block_writes(after=1)
    result = hid.wake("key", device=blank_device, key="enter", hold_ms=1)
    assert result["warnings"] == ["warn.release_blocked"]


def test_send_signal_tolerates_suspension(blank_device, block_writes):
    block_writes(after=0)
    step, warnings = hid.send_signal(blank_device)
    assert step == "step.zero_report"
    assert warnings == ["warn.no_wakeup_patch", "err.bus.suspended"]
