"""Small helpers shared by the test modules.

各测试模块共用的小工具。
"""

import random
import string
from pathlib import Path

import i18n


def read_device(path):
    """Return the raw bytes written to the stand-in HID device.

    返回写入替代 HID 设备的原始字节。
    """
    return Path(path).read_bytes()


def blank_device(path):
    """Empty the stand-in device.

    清空替代设备。
    """
    Path(path).write_bytes(b"")
    return path


def catalogs():
    """Return (en, zh-CN) message catalogs.

    返回 (en, zh-CN) 两个消息目录。
    """
    return i18n.CATALOGS["en"], i18n.CATALOGS["zh-CN"]


def make_request(path="/", method="GET", headers=None, query=None, data=None,
                 content_type=None):
    """Build a Flask Request without going through the test client.

    直接构造 Flask Request，不经过测试客户端。
    """
    from flask import Request
    from werkzeug.test import EnvironBuilder

    builder = EnvironBuilder(path=path, method=method, query_string=query,
                             headers=headers, data=data, content_type=content_type)
    return Request(builder.get_environ())


def set_cookie_sizes(response):
    """Lengths of every Set-Cookie header on the response, longest first.

    响应上每条 Set-Cookie 的长度，从长到短。
    """
    return sorted((len(c) for c in response.headers.getlist("Set-Cookie")), reverse=True)


def random_key(length, seed=1234):
    """A key string that is neither valid nor compressible.

    It avoids '+' because that is the chord separator, and avoids repeating
    patterns so that session-cookie compression cannot hide the size.

    既非法又不可压缩的按键字符串。不含 '+'（那是组合键分隔符），也不含重复
    模式，避免会话 cookie 的压缩掩盖真实体积。
    """
    rng = random.Random(seed)
    return "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(length))
