"""Read and write USB HID keyboard reports, and drive the wake-up sequence.

The device node comes from the host-side configfs gadget
(see host/setup-hid-gadget.sh). This module only writes 8-byte keyboard
reports to /dev/hidg0. It stays language-agnostic: failures carry a message
key plus its parameters, and the web layer translates them.

读写 USB HID 键盘报文，并执行唤醒流程。

设备节点由宿主机的 configfs gadget 提供（见 host/setup-hid-gadget.sh），
本模块只负责往 /dev/hidg0 写 8 字节键盘报文。本模块与语言无关：失败时
只带出消息键和参数，由 Web 层负责翻译。
"""

import errno
import glob
import os
import threading
import time

REPORT_LENGTH = 8

WAKEUP_PARAM = "/sys/module/usb_f_hid/parameters/wakeup_on_write"
CONFIGFS_ROOT = "/sys/kernel/config/usb_gadget"

WRITE_RETRIES = 5
RELEASE_RETRIES = 15
WRITE_RETRY_DELAY = 0.02
REBIND_WAIT = 3.0

MODIFIERS = {
    "ctrl": 0x01,
    "lctrl": 0x01,
    "shift": 0x02,
    "lshift": 0x02,
    "alt": 0x04,
    "lalt": 0x04,
    "meta": 0x08,
    "lmeta": 0x08,
    "rctrl": 0x10,
    "rshift": 0x20,
    "ralt": 0x40,
    "rmeta": 0x80,
}

KEYMAP = {
    "enter": 0x28,
    "esc": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "minus": 0x2D,
    "equal": 0x2E,
    "capslock": 0x39,
    "delete": 0x4C,
    "insert": 0x49,
    "home": 0x4A,
    "end": 0x4D,
    "pageup": 0x4B,
    "pagedown": 0x4E,
    "right": 0x4F,
    "left": 0x50,
    "down": 0x51,
    "up": 0x52,
    "numlock": 0x53,
    "kpenter": 0x58,
}

# Letters a-z, digits 0-9 and F1-F12 sit at fixed HID usage offsets.
#
# 字母 a-z、数字 0-9 与 F1-F12 的码值位于固定的 HID usage 偏移上。
KEYMAP.update({chr(ord("a") + i): 0x04 + i for i in range(26)})
KEYMAP.update({str((i + 1) % 10): 0x1E + i for i in range(10)})
KEYMAP.update({"f%d" % i: 0x39 + i for i in range(1, 13)})

_lock = threading.Lock()


class HIDError(RuntimeError):
    """An expected failure, carrying a message key and its parameters.

    The web layer turns this into a 503-style response in the caller's
    language, so str() is just the key and is meant for logs.

    唤醒过程中可预期的失败，携带消息键与参数。

    Web 层会按调用方的语言把它转成 503 之类的结果，因此 str() 只是消息键，
    仅用于日志。
    """

    def __init__(self, key, **params):
        super().__init__(key)
        self.key = key
        self.params = params


class BusSuspended(HIDError):
    """The bus is suspended: reports are queued but the host never collects them.

    A non-blocking write returns EAGAIN while the previous request has not
    been collected yet. A sleeping target stops polling the interrupt
    endpoint, so that state simply persists. The report is already queued by
    then, so this must not be reported as "device unusable".

    总线挂起：目标机可能正在睡眠，报文已排队但主机不会来取。

    非阻塞写入返回 EAGAIN 表示上一个请求还没被主机取走。目标机睡眠时
    主机会停止轮询中断端点，于是这个状态会一直持续——此时报文其实已
    经排进队列，不应该当成「设备不可用」来报错。
    """


class InvalidInput(HIDError):
    """The request itself is wrong: an unknown key or mode, a bad repeat count.

    The web layer answers these with 400, while device trouble stays a 503, so
    a typo in the UI and an unplugged cable are distinguishable in monitoring.

    请求本身有误：按键或模式无法识别、重复次数不合法。

    Web 层对这些返回 400，而设备侧问题仍然是 503，这样界面上的笔误和线没插好
    在监控里能区分开。
    """


def parse_key(spec):
    """Parse 'ctrl+shift+enter' into (modifier byte, key code).

    把 'ctrl+shift+enter' 解析为 (修饰键字节, 按键码)。
    """
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if not parts:
        raise InvalidInput("err.key.empty")

    modifier = 0
    for part in parts[:-1]:
        if part not in MODIFIERS:
            raise InvalidInput("err.modifier.unknown", name=part)
        modifier |= MODIFIERS[part]

    # A trailing modifier means "modifier with no key", which is not a keypress.
    # This is checked after the loop above so that a typo in a leading modifier
    # is still reported as an unknown modifier.
    #
    # 末尾是修饰键说明「只有修饰键、没有按键」，那不是一个有效的按键。
    # 这一检查放在上面的循环之后，这样前缀里的拼写错误仍会报成未知修饰键。
    if parts[-1] in MODIFIERS:
        raise InvalidInput("err.key.empty")

    code = KEYMAP.get(parts[-1])
    if code is None:
        raise InvalidInput("err.key.unknown", name=parts[-1])
    return modifier, code


def device_ready(device):
    return os.path.exists(device)


def wakeup_supported():
    return os.path.exists(WAKEUP_PARAM)


def udc_state():
    """/sys/class/udc/*/state, e.g. configured / suspended / not attached.

    读取 /sys/class/udc/*/state，例如 configured / suspended / not attached。
    """
    for path in sorted(glob.glob("/sys/class/udc/*/state")):
        try:
            with open(path) as handle:
                return handle.read().strip()
        except OSError:
            continue
    return None


def _open(device):
    """Open the HID device in non-blocking mode.

    Blocking mode would hang forever on a suspended bus, so O_NONBLOCK plus
    the retry loop in _write() is deliberate.

    以非阻塞方式打开 HID 设备。

    阻塞模式下总线挂起时写入会永久卡住，所以这里刻意使用 O_NONBLOCK，
    由 _write() 里的重试循环负责等待。
    """
    if not os.path.exists(device):
        raise HIDError("err.device.missing", device=device)
    try:
        return os.open(device, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        raise HIDError("err.device.open", device=device, error=exc.strerror) from exc


def _write(fd, report, retries=WRITE_RETRIES):
    """Write one report, telling «device unusable» apart from «bus suspended».

    写一条报文，区分「设备不可用」和「总线挂起」。
    """
    busy = False
    for _ in range(retries):
        try:
            if os.write(fd, report) == len(report):
                return
        except BlockingIOError:
            busy = True
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EBUSY):
                busy = True
            elif exc.errno == errno.ESHUTDOWN:
                raise HIDError("err.device.disabled", error=exc.strerror) from exc
            else:
                raise HIDError("err.device.write", error=exc.strerror) from exc
        time.sleep(WRITE_RETRY_DELAY)

    if busy:
        raise BusSuspended("err.bus.suspended")
    raise HIDError("err.report.length")


def press_key(device, key, hold_ms=60, repeat=1):
    """Press a key once: press, hold, release.

    Returns None when everything was delivered. Returns "press_blocked" when
    the press report could not even be queued (an earlier report is still
    waiting to be collected). Returns "release_blocked" when the press was
    queued but the host never came for the release. Both blocked results mean
    the target is asleep.

    f_hid has a single request slot on its IN endpoint, so a suspended bus can
    only ever hold one report.

    按一次键：按下 -> 保持 -> 释放。

    返回 None 表示完整送达；返回 "press_blocked" 表示按下报文没能排队
    （队列里还有上次未被主机取走的报文）；返回 "release_blocked" 表示按下
    已排队、但主机没来取释放报文。后两种情况都说明目标机在睡觉。

    f_hid 的 IN 端点只有一个请求缓冲位，所以总线挂起时只可能排进一条报文。
    """
    modifier, code = parse_key(key)
    if not 1 <= repeat <= 5:
        raise InvalidInput("err.repeat.range")
    press = bytes([modifier, 0, code, 0, 0, 0, 0, 0])
    release = bytes(REPORT_LENGTH)
    with _lock:
        fd = _open(device)
        try:
            for _ in range(repeat):
                try:
                    _write(fd, press)
                except BusSuspended:
                    return "press_blocked"
                time.sleep(hold_ms / 1000.0)
                try:
                    _write(fd, release, retries=RELEASE_RETRIES)
                except BusSuspended:
                    return "release_blocked"
                if repeat > 1:
                    time.sleep(hold_ms / 1000.0)
        finally:
            os.close(fd)
    return None


def _enable_wakeup_on_write():
    """Turn on wakeup_on_write if the kernel has it.

    The JetKVM f_hid patch calls usb_gadget_wakeup() on write; mainline
    kernels have no such patch.

    若内核有这个参数，就打开 wakeup_on_write。

    JetKVM 的 f_hid 补丁会在写入时调用 usb_gadget_wakeup()，主线内核没有这个补丁。
    """
    if not os.path.exists(WAKEUP_PARAM):
        return False
    try:
        with open(WAKEUP_PARAM) as handle:
            if handle.read().strip() == "1":
                return True
        with open(WAKEUP_PARAM, "w") as handle:
            handle.write("1\n")
        return True
    except OSError:
        return False


def _rebind_udc(device, gadget_name):
    """Unbind and rebind the UDC: the software equivalent of replugging the keyboard.

    解绑再绑回 UDC，等效于拔插一次键盘。
    """
    udc_file = os.path.join(CONFIGFS_ROOT, gadget_name, "UDC")
    if not os.path.exists(udc_file):
        return False
    try:
        with open(udc_file) as handle:
            udc = handle.read().strip()
        if not udc:
            return False
        with open(udc_file, "w") as handle:
            handle.write("\n")
        time.sleep(0.3)
        with open(udc_file, "w") as handle:
            handle.write(udc + "\n")
    except OSError:
        return False

    deadline = time.time() + REBIND_WAIT
    while time.time() < deadline and not os.path.exists(device):
        time.sleep(0.1)
    return os.path.exists(device)


def send_signal(device, enable_rebind=False, gadget_name="hidwake"):
    """Send a wake-up signal without producing any keystroke.

    Returns (step key, list of warning keys).

    只发唤醒信号，不产生任何按键。返回 (步骤消息键, 警告消息键列表)。
    """
    with _lock:
        if _enable_wakeup_on_write():
            fd = _open(device)
            try:
                _write(fd, bytes(REPORT_LENGTH))
            except BusSuspended:
                return "step.wakeup_on_write", ["err.bus.suspended"]
            finally:
                os.close(fd)
            return "step.wakeup_on_write", []

        if enable_rebind and _rebind_udc(device, gadget_name):
            return "step.udc_rebind", []

        warnings = ["warn.no_wakeup_patch"]
        fd = _open(device)
        try:
            _write(fd, bytes(REPORT_LENGTH))
        except BusSuspended:
            warnings.append("err.bus.suspended")
        finally:
            os.close(fd)
        return "step.zero_report", warnings


def wake(mode, device, key="enter", repeat=1, hold_ms=60,
         enable_rebind=False, gadget_name="hidwake"):
    """Run the wake-up sequence and return a result dict of message keys.

    The dict holds "steps" as {key, params} entries and "warnings" as message
    keys; the web layer renders both in the caller's language.

    执行唤醒流程，返回由消息键组成的结果字典。

    字典里的 "steps" 是 {key, params} 列表，"warnings" 是消息键列表，
    两者都由 Web 层按调用方的语言渲染。
    """
    if mode not in ("key", "signal", "both"):
        raise InvalidInput("err.mode.unknown", mode=mode)

    result = {"mode": mode, "key": key, "repeat": repeat, "steps": [], "warnings": []}

    if mode in ("signal", "both"):
        step, warnings = send_signal(device, enable_rebind, gadget_name)
        result["steps"].append({"key": step})
        result["warnings"].extend(warnings)

    if mode in ("key", "both"):
        status = press_key(device, key, hold_ms, repeat)
        if status == "release_blocked":
            result["warnings"].append("warn.release_blocked")
        elif status == "press_blocked":
            result["warnings"].append("warn.press_blocked")
        result["steps"].append({"key": "step.key", "params": {"key": key, "repeat": repeat}})

    return result
