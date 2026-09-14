"""Flask app for the USB HID web waker.

Output is bilingual. The language is resolved per request in this order: an
explicit `lang` parameter, the remembered cookie, the browser's system
language, the APP_LANG container variable, then English as the last resort.

USB HID 网页唤醒器的 Flask 应用。

输出支持双语。每次请求按以下顺序确定语言：显式 `lang` 参数 > 记住的 cookie >
浏览器系统语言 > 容器变量 APP_LANG > 英文保底。
"""

import os
import secrets
import threading
import time
from datetime import timedelta

from flask import (Flask, abort, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import hid
import i18n

# Startup happens before any request exists, so these messages follow APP_LANG
# and otherwise fall back to English.
#
# 启动发生在任何请求之前，因此这些消息遵循 APP_LANG，否则回退英文。
_startup = i18n.default_translator()

# Bounds that keep a typo in .env from turning into a request-time failure, and
# keep a long input from being echoed into the signed session cookie.
#
# 这些上限让 .env 里的笔误在启动时就暴露，而不是等到请求；同时避免超长输入
# 被回显进签名会话 cookie。
MAX_KEY_LENGTH = 32
MAX_MODE_LENGTH = 16
MAX_REPEAT = 5
MAX_HOLD_MS = 2000
MAX_CONTENT_LENGTH = 64 * 1024

# Labels live in the catalogs under "mode.<key>".
#
# 显示名放在消息目录的 "mode.<key>" 下。
MODE_KEYS = ("key", "signal", "both")

KEY_CHOICES = [
    "enter", "space", "esc", "tab", "backspace",
    "a", "b", "c", "d", "e", "f", "h", "k", "m", "p", "s", "w",
    "0", "1", "2",
    "f1", "f2", "f10", "f12",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown", "delete",
    "ctrl+enter", "ctrl+shift+enter", "alt+enter", "shift+space",
]


def _env_int(name, default, minimum=None, maximum=None):
    """Read an integer environment variable, rejecting anything unusable.

    读取整数型环境变量，取值不可用时直接报错。
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(_startup("startup.bad_env_int", name=name, value=raw)) from None
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise RuntimeError(_startup("startup.bad_env_range", name=name, value=raw,
                                    minimum=minimum, maximum=maximum))
    return value


def _validated_mode(value):
    """Reject a WAKE_MODE that no request could ever use.

    校验 WAKE_MODE，任何请求都用不了的取值直接拒绝。
    """
    if value not in MODE_KEYS:
        raise RuntimeError(_startup("startup.bad_mode", value=value))
    return value


def _validated_key(value):
    """Reject a WAKE_KEY that the key parser cannot handle.

    校验 WAKE_KEY，解析器认不出的取值直接拒绝。
    """
    try:
        hid.parse_key(value)
    except hid.HIDError as exc:
        raise RuntimeError(
            _startup("startup.bad_key", error=_startup(exc.key, **exc.params))
        ) from None
    return value


APP_USER = os.environ.get("APP_USER", "admin")
PASSWORD_HASH = os.environ.get("APP_PASSWORD_HASH", "").strip()
if not PASSWORD_HASH:
    _plain = os.environ.get("APP_PASSWORD", "")
    if not _plain:
        raise RuntimeError(_startup("startup.missing_password"))
    PASSWORD_HASH = generate_password_hash(_plain)

SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise RuntimeError(_startup("startup.missing_secret"))

HID_DEVICE = os.environ.get("HID_DEVICE", "/dev/hidg0")
GADGET_NAME = os.environ.get("GADGET_NAME", "hidwake")
ENABLE_UDC_REBIND = os.environ.get("ENABLE_UDC_REBIND", "0") == "1"

# Set COOKIE_SECURE=1 when the app is served over HTTPS, so the session and
# language cookies are never sent over plain HTTP.
#
# 走 HTTPS 时把 COOKIE_SECURE 置 1，会话与语言 cookie 就不会走明文 HTTP。
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

DEFAULT_MODE = _validated_mode(os.environ.get("WAKE_MODE", "both"))
DEFAULT_KEY = _validated_key(os.environ.get("WAKE_KEY", "enter"))
DEFAULT_REPEAT = _env_int("WAKE_REPEAT", 1, minimum=1, maximum=MAX_REPEAT)
KEY_HOLD_MS = _env_int("KEY_HOLD_MS", 60, minimum=1, maximum=MAX_HOLD_MS)

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(hours=12)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=COOKIE_SECURE,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
)

# Failed logins are counted per source IP inside a rolling window, so that one
# attacker cannot slow down every other client.
#
# 登录失败按来源 IP 在滑动时间窗内计数，避免一个攻击者拖慢其他所有客户端。
FAILED_LOGIN_LIMIT = 3
FAILED_LOGIN_WINDOW = 300.0
FAILED_LOGIN_DELAY = 1.0
MAX_TRACKED_SOURCES = 2048

_login_failures = {}
_login_failures_lock = threading.Lock()

# Consulted even when the username is wrong, so that response time does not
# reveal whether an account exists.
#
# 用户名错误时也会拿它比较一次，避免用响应时间判断账号是否存在。
_DUMMY_PASSWORD_HASH = generate_password_hash("dummy-password-not-a-real-credential")


def _verify_credentials(username, password):
    """Check both fields without leaking which one was wrong via timing.

    校验用户名和密码，避免通过响应时间泄露是哪一项错误。
    """
    if username == APP_USER:
        return check_password_hash(PASSWORD_HASH, password)
    check_password_hash(_DUMMY_PASSWORD_HASH, password)
    return False


def _record_login_failure(source):
    now = time.time()
    with _login_failures_lock:
        expired = [key for key, stamps in _login_failures.items()
                   if not [t for t in stamps if now - t < FAILED_LOGIN_WINDOW]]
        for key in expired:
            del _login_failures[key]
        if source not in _login_failures and len(_login_failures) >= MAX_TRACKED_SOURCES:
            _login_failures.clear()
        _login_failures.setdefault(source, []).append(now)


def _clear_login_failures(source):
    with _login_failures_lock:
        _login_failures.pop(source, None)


def _login_throttled(source):
    now = time.time()
    with _login_failures_lock:
        recent = [t for t in _login_failures.get(source, []) if now - t < FAILED_LOGIN_WINDOW]
        if recent:
            _login_failures[source] = recent
        else:
            _login_failures.pop(source, None)
        return len(recent) >= FAILED_LOGIN_LIMIT


# Endpoints reachable without logging in. Everything else is protected, so a
# forgotten decorator cannot leave a route open.
#
# 无需登录即可访问的端点。其余一律受保护，因此漏写装饰器也不会留下敞开的接口。
PUBLIC_ENDPOINTS = {"login", "static"}


# Registered before the CSRF hook so that g.t is ready when it runs.
#
# 注册在 CSRF 钩子之前，保证它执行时 g.t 已就绪。
@app.before_request
def _set_language():
    g.lang, g.lang_source = i18n.resolve(request)
    g.t = i18n.Translator(g.lang)


@app.after_request
def _persist_language(response):
    """Remember an explicit choice so that later requests keep it.

    Only a manual `lang` parameter writes the cookie; a language guessed from
    the browser stays a guess and is free to change with the browser.

    记住显式选择，使后续请求沿用它。

    只有手动传入的 `lang` 参数才写 cookie；由浏览器探测得到的语言仍然只是
    探测结果，可以随浏览器设置变化。
    """
    if g.get("lang_source") == "manual":
        response.set_cookie(
            i18n.COOKIE_NAME,
            g.lang,
            max_age=i18n.COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=COOKIE_SECURE,
        )
    return response


# Runs before the CSRF hook: an unauthenticated POST should be sent to the
# login page, not reported as a CSRF failure.
#
# 排在 CSRF 钩子之前：未登录的 POST 应该跳转到登录页，而不是被报成 CSRF 校验失败。
@app.before_request
def _require_login():
    endpoint = request.endpoint
    if endpoint is None or endpoint in PUBLIC_ENDPOINTS:
        return None
    if not session.get("user"):
        return redirect(url_for("login"))
    return None


@app.before_request
def _require_csrf():
    if request.method == "POST" and not _csrf_valid():
        abort(400, description=g.t("err.csrf"))


@app.context_processor
def _inject_i18n():
    return {
        "t": g.t,
        "lang": g.lang,
        "languages": i18n.SUPPORTED_LANGS,
        "modes": MODE_KEYS,
    }


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def _csrf_valid():
    expected = session.get("_csrf")
    provided = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
    return bool(expected) and secrets.compare_digest(expected, provided)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        source = request.remote_addr or "unknown"
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if _verify_credentials(username, password):
            _clear_login_failures(source)
            session.clear()
            session.permanent = True
            session["user"] = APP_USER
            return redirect(url_for("index"))
        _record_login_failure(source)
        if _login_throttled(source):
            time.sleep(FAILED_LOGIN_DELAY)
        error = g.t("err.login")
    return render_template("login.html", error=error, csrf_token=csrf_token())


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return render_template(
        "index.html",
        keys=KEY_CHOICES,
        default_mode=DEFAULT_MODE,
        default_key=DEFAULT_KEY,
        default_repeat=DEFAULT_REPEAT,
        device=HID_DEVICE,
        device_ready=hid.device_ready(HID_DEVICE),
        udc_state=hid.udc_state(),
        wakeup_supported=hid.wakeup_supported(),
        rebind_enabled=ENABLE_UDC_REBIND,
        last=session.pop("last_result", None),
        csrf_token=csrf_token(),
    )


def _payload():
    """Return the request parameters, or None when the body is unusable.

    A JSON request must carry a JSON object. An array, a bare string,
    malformed JSON or an empty body is a client error, not a silent fallback
    to the defaults — that used to fire a real wake for an unparseable request.

    返回请求参数；请求体不可用时返回 None。

    JSON 请求必须携带 JSON 对象。数组、裸字符串、畸形 JSON、空请求体都属于
    客户端错误，而不是静默回退到默认值 —— 后者会让一个无法解析的请求真的
    触发唤醒。
    """
    if request.is_json:
        payload = request.get_json(silent=True)
        return payload if isinstance(payload, dict) else None
    return request.form


def _text_field(payload, name, default, maximum):
    """Return a validated string field, or None when it is unusable.

    返回校验过的字符串字段，不可用时返回 None。
    """
    value = payload.get(name)
    if value is None or value == "":
        return default
    if not isinstance(value, str) or len(value) > maximum:
        return None
    return value.strip()


def _repeat_field(payload):
    """Return (repeat, error_response). Exactly one of them is set.

    返回 (重复次数, 错误响应)，两者中只有一个有值。
    """
    raw = payload.get("repeat")
    if raw is None or raw == "":
        repeat = DEFAULT_REPEAT
    else:
        # bool is a subclass of int, so it has to be excluded explicitly.
        #
        # bool 是 int 的子类，必须显式排除。
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            return None, ({"ok": False, "error": g.t("err.repeat.number")}, 400)
        try:
            repeat = int(raw)
        except ValueError:
            return None, ({"ok": False, "error": g.t("err.repeat.number")}, 400)
    if not 1 <= repeat <= MAX_REPEAT:
        return None, ({"ok": False, "error": g.t("err.repeat.range")}, 400)
    return repeat, None


def _do_wake():
    payload = _payload()
    if payload is None:
        return {"ok": False, "error": g.t("err.payload")}, 400

    mode = _text_field(payload, "mode", DEFAULT_MODE, MAX_MODE_LENGTH)
    if mode is None or mode not in MODE_KEYS:
        return {"ok": False, "error": g.t("err.mode.invalid")}, 400

    key = _text_field(payload, "key", DEFAULT_KEY, MAX_KEY_LENGTH)
    if key is None:
        return {"ok": False, "error": g.t("err.key.invalid", maximum=MAX_KEY_LENGTH)}, 400

    repeat, failure = _repeat_field(payload)
    if failure is not None:
        return failure

    try:
        result = hid.wake(
            mode=mode,
            device=HID_DEVICE,
            key=key,
            repeat=repeat,
            hold_ms=KEY_HOLD_MS,
            enable_rebind=ENABLE_UDC_REBIND,
            gadget_name=GADGET_NAME,
        )
    except hid.InvalidInput as exc:
        return {"ok": False, "error": g.t(exc.key, **exc.params)}, 400
    except hid.HIDError as exc:
        return {"ok": False, "error": g.t(exc.key, **exc.params)}, 503

    result["steps"] = [g.t(step["key"], **step.get("params", {})) for step in result["steps"]]
    result["warnings"] = [g.t(warning) for warning in result["warnings"]]
    result["lang"] = g.lang
    result["ok"] = True
    return result, 200


@app.route("/wake", methods=["POST"])
def wake_form():
    result, status = _do_wake()
    if status == 200:
        message = g.t("ui.flash.sent", steps=" → ".join(result["steps"]))
        for warning in result["warnings"]:
            message += " " + warning
    else:
        message = result.get("error", g.t("ui.flash.failed"))
    session["last_result"] = {"ok": status == 200, "message": message}
    return redirect(url_for("index"))


@app.route("/api/status")
def api_status():
    return jsonify(
        lang=g.lang,
        ready=hid.device_ready(HID_DEVICE),
        device=HID_DEVICE,
        udc_state=hid.udc_state(),
        wakeup_supported=hid.wakeup_supported(),
    )


@app.route("/api/wake", methods=["POST"])
def api_wake():
    result, status = _do_wake()
    return jsonify(result), status
