"""Language resolution and message lookup for the web layer.

Priority: an explicit `lang` parameter, then the system language
(Accept-Language), then English as the guaranteed fallback.

语言解析与消息查表。

优先级：显式 `lang` 参数 > 系统语言（Accept-Language）> 英文保底。
"""

import json
import os

DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("en", "zh-CN")
LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")

# The cookie remembers a manual choice so that it survives later requests.
# It carries no auth state, so clearing the session leaves it alone.
#
# cookie 用来记住手动选择，使其在后续请求中保持。它不承载认证状态，
# 因此清空会话不会影响它。
COOKIE_NAME = "lang"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# Only the primary subtag decides the language, so "zh", "zh_CN" and
# "zh-Hans-CN" all land on zh-CN, while "en-GB" lands on en.
#
# 只用主语言子标签判定，因此 "zh"、"zh_CN"、"zh-Hans-CN" 都归到 zh-CN，
# 而 "en-GB" 归到 en。
_PRIMARY = {"en": "en", "zh": "zh-CN"}


def _load(lang):
    path = os.path.join(LOCALES_DIR, "%s.json" % lang)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# The catalogs are small and read-only, so load them once at import time.
#
# 目录很小且只读，在导入时一次性加载。
CATALOGS = {lang: _load(lang) for lang in SUPPORTED_LANGS}


def normalize(code):
    """Map a language tag onto a supported one, or None when unknown.

    "en-GB" -> "en", "zh-Hans-CN" -> "zh-CN", "fr" -> None.

    Anything that is not a string is rejected rather than raising: a JSON body
    can carry any type for `lang`, and this runs before authentication.

    把语言标签归一化为受支持的值，无法识别时返回 None。

    非字符串一律拒绝而不是抛异常：JSON 请求体里的 `lang` 可以是任意类型，
    而这段逻辑在鉴权之前就会执行。
    """
    if not isinstance(code, str):
        return None
    tag = code.strip().replace("_", "-").lower()
    if tag in CATALOGS:
        return tag
    return _PRIMARY.get(tag.split("-")[0])


def _manual_lang(request):
    """Yield the explicit `lang` values from body, query, form and header.

    依次产出请求体、查询串、表单和请求头里的显式 `lang` 值。
    """
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        yield payload.get("lang")
    yield request.args.get("lang")
    yield request.form.get("lang")
    yield request.headers.get("X-Lang")


def resolve(request):
    """Return (lang, source) for this request.

    Sources, in priority order:

    1. "manual"  — an explicit `lang` parameter, also stored as a cookie;
    2. "cookie"  — the remembered manual choice;
    3. "system"  — the browser's Accept-Language;
    4. "env"     — the APP_LANG container variable, for callers with no system
                   language at all (curl, cron, scripts);
    5. "default" — English.

    返回 (语言, 来源)。来源按优先级为：

    1. "manual"  —— 显式 `lang` 参数，同时会写进 cookie；
    2. "cookie"  —— 之前手动选择并记住的语言；
    3. "system"  —— 浏览器的 Accept-Language；
    4. "env"     —— 容器变量 APP_LANG，供完全没有系统语言的调用方
                    （curl、cron、脚本）使用；
    5. "default" —— 英文。
    """
    for value in _manual_lang(request):
        lang = normalize(value)
        if lang:
            return lang, "manual"

    lang = normalize(request.cookies.get(COOKIE_NAME))
    if lang:
        return lang, "cookie"

    lang = normalize(request.accept_languages.best_match(SUPPORTED_LANGS))
    if lang:
        return lang, "system"

    lang = normalize(os.environ.get("APP_LANG"))
    if lang:
        return lang, "env"

    return DEFAULT_LANG, "default"


def default_translator():
    """Translator for messages outside a request, such as container startup.

    Runs before any request exists, hence APP_LANG or English.

    供请求之外的消息（例如容器启动）使用的翻译器。

    此时还没有任何请求，因此用 APP_LANG 或英文。
    """
    return Translator(normalize(os.environ.get("APP_LANG")) or DEFAULT_LANG)


class Translator:
    """Look a message key up in the chosen catalog, falling back to English.

    在选定语言的目录里查消息键，缺失时回退到英文。
    """

    def __init__(self, lang):
        self.lang = lang
        self._catalog = CATALOGS.get(lang, CATALOGS[DEFAULT_LANG])

    def __call__(self, message_key, /, **params):
        """Look `message_key` up and interpolate `params` into it.

        `message_key` is positional-only on purpose: a message may well have a
        placeholder named `key`, and that must not collide with the argument
        name.

        按 `message_key` 查表，并把 `params` 插值进去。

        `message_key` 刻意声明为仅位置参数：消息里可能存在名为 `key` 的占位符，
        不能和参数名冲突。
        """
        text = self._catalog.get(message_key)
        if text is None:
            text = CATALOGS[DEFAULT_LANG].get(message_key, message_key)
        return text.format(**params)
