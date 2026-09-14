"""Language resolution, message catalogs and the cookie/env fallbacks.

语言解析、消息目录，以及 cookie / 环境变量的保底行为。
"""

import json
import re
import string
from pathlib import Path

import pytest

import app as appmod
import i18n
from helpers import catalogs, make_request

ROOT = Path(__file__).resolve().parent.parent

ZH_BROWSER = {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
EN_BROWSER = {"Accept-Language": "en-US,en;q=0.9"}


# ---------- normalize ----------

@pytest.mark.parametrize("raw,expected", [
    ("en", "en"), ("EN", "en"), ("en-US", "en"), ("en_GB", "en"), ("en-GB", "en"),
    ("zh", "zh-CN"), ("zh-CN", "zh-CN"), ("zh_cn", "zh-CN"), ("zh-CN", "zh-CN"),
    ("zh-Hans", "zh-CN"), ("zh-Hans-CN", "zh-CN"), ("zh-SG", "zh-CN"), ("zh-TW", "zh-CN"),
    ("  zh-CN  ", "zh-CN"),
    ("fr", None), ("de-DE", None), ("", None), (None, None),
])
def test_normalize(raw, expected):
    assert i18n.normalize(raw) == expected


@pytest.mark.parametrize("value", [123, 1.5, True, False, ["en"], {"a": 1}, b"en", object()])
def test_normalize_rejects_non_strings(value):
    """A JSON body can carry any type for `lang`; it must not raise.

    JSON 请求体里的 `lang` 可以是任意类型，不能因此抛异常。
    """
    assert i18n.normalize(value) is None


# ---------- 优先级 ----------

def test_no_information_falls_back_to_english():
    assert i18n.resolve(make_request()) == ("en", "default")


def test_system_language_from_accept_language():
    assert i18n.resolve(make_request(headers=ZH_BROWSER)) == ("zh-CN", "system")
    assert i18n.resolve(make_request(headers=EN_BROWSER)) == ("en", "system")


def test_unsupported_system_language_falls_back_to_english():
    request = make_request(headers={"Accept-Language": "fr-FR,fr;q=0.9"})
    assert i18n.resolve(request) == ("en", "default")


@pytest.mark.parametrize("kwargs,expected", [
    ({"query": {"lang": "en"}, "headers": ZH_BROWSER}, ("en", "manual")),
    ({"query": {"lang": "zh-CN"}, "headers": EN_BROWSER}, ("zh-CN", "manual")),
    ({"query": {"lang": "zh_Hans"}}, ("zh-CN", "manual")),
    ({"query": {"lang": "fr"}, "headers": ZH_BROWSER}, ("zh-CN", "system")),
    ({"query": {"lang": "123"}}, ("en", "default")),
    ({"method": "POST", "data": {"lang": "zh-CN"}, "headers": EN_BROWSER}, ("zh-CN", "manual")),
    ({"method": "POST", "data": json.dumps({"lang": "zh-CN"}),
      "content_type": "application/json", "headers": EN_BROWSER}, ("zh-CN", "manual")),
    ({"method": "POST", "data": json.dumps({"lang": 123}),
      "content_type": "application/json", "headers": ZH_BROWSER}, ("zh-CN", "system")),
    ({"headers": {**EN_BROWSER, "X-Lang": "zh-CN"}}, ("zh-CN", "manual")),
])
def test_manual_parameter_wins(kwargs, expected):
    assert i18n.resolve(make_request(**kwargs)) == expected


def test_cookie_ranks_between_manual_and_system(monkeypatch):
    assert i18n.resolve(make_request(headers={**EN_BROWSER, "Cookie": "lang=zh-CN"})) == ("zh-CN", "cookie")
    assert i18n.resolve(make_request(query={"lang": "en"},
                                     headers={**EN_BROWSER, "Cookie": "lang=zh-CN"})) == ("en", "manual")
    assert i18n.resolve(make_request(headers={**ZH_BROWSER, "Cookie": "lang=en"})) == ("en", "cookie")
    assert i18n.resolve(make_request(headers={**ZH_BROWSER, "Cookie": "lang=fr"})) == ("zh-CN", "system")
    assert i18n.resolve(make_request(headers={**EN_BROWSER, "Cookie": "session=abc; lang=zh-CN"})) == ("zh-CN", "cookie")


def test_app_lang_environment_variable(monkeypatch):
    monkeypatch.setenv("APP_LANG", "zh-CN")
    assert i18n.resolve(make_request()) == ("zh-CN", "env")
    assert i18n.resolve(make_request(headers=ZH_BROWSER)) == ("zh-CN", "system"), "系统语言优先"

    monkeypatch.setenv("APP_LANG", "zh_Hans")
    assert i18n.resolve(make_request()) == ("zh-CN", "env")

    monkeypatch.setenv("APP_LANG", "fr")
    assert i18n.resolve(make_request()) == ("en", "default")


def test_default_translator_follows_app_lang(monkeypatch):
    english, chinese = catalogs()
    assert i18n.default_translator()("err.login") == english["err.login"]
    monkeypatch.setenv("APP_LANG", "zh-CN")
    assert i18n.default_translator()("err.login") == chinese["err.login"]


# ---------- 消息目录 ----------

def test_catalogs_cover_the_same_keys():
    english, chinese = catalogs()
    assert set(english) == set(chinese)
    assert len(english) > 30


def test_english_catalog_is_english_apart_from_language_names():
    english, _ = catalogs()
    # Language names are shown in their own language, which is deliberate.
    #
    # 语言名按各自语言显示，属于刻意的例外。
    assert {k for k, v in english.items() if re.search(r"[\u4e00-\u9fff]", v)} == {"ui.lang.zh-CN"}


def test_placeholders_match_between_languages():
    english, chinese = catalogs()

    def placeholders(text):
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    mismatched = {k: (sorted(placeholders(english[k])), sorted(placeholders(chinese[k])))
                  for k in english
                  if placeholders(english[k]) != placeholders(chinese[k])}
    assert not mismatched


def test_every_message_formats():
    english, chinese = catalogs()
    broken = []
    for catalog in (english, chinese):
        for key, text in catalog.items():
            names = {name for _, name, _, _ in string.Formatter().parse(text) if name}
            try:
                text.format(**{name: "X" for name in names})
            except (KeyError, IndexError, ValueError) as exc:
                broken.append((key, str(exc)))
    assert not broken


def test_every_key_used_in_code_exists():
    english, _ = catalogs()
    used = set()
    for rel in ("app.py", "hid.py"):
        source = (ROOT / rel).read_text(encoding="utf-8")
        used |= set(re.findall(r'(?<![\w.])"((?:err|warn|step|startup)\.[a-z._]+)"', source))
        used |= set(re.findall(r'(?<![\w.])t\("([a-z][a-z0-9._-]+)"\)', source))
    for name in ("index.html", "login.html"):
        source = (ROOT / "templates" / name).read_text(encoding="utf-8")
        used |= set(re.findall(r'(?<![\w.])t\("([a-z][a-z0-9._-]+)"\)', source))
    assert used, "没有扫描到任何键，检查正则"
    assert not (used - set(english)), "代码引用了目录里不存在的键"


def test_dynamically_built_keys_exist():
    english, _ = catalogs()
    assert not [code for code in i18n.SUPPORTED_LANGS if "ui.lang." + code not in english]
    assert not [mode for mode in appmod.MODE_KEYS if "mode." + mode not in english]


# ---------- 端到端 ----------

def test_login_page_follows_browser_language(client):
    chinese = client.get("/login", headers=ZH_BROWSER).data.decode()
    english = client.get("/login", headers=EN_BROWSER).data.decode()
    assert "用户名" in chinese and "Username" not in chinese
    assert "Username" in english and "用户名" not in english
    assert '<html lang="zh-CN">' in chinese
    assert '<html lang="en">' in english
    assert 'href="/login?lang=zh-CN"' in chinese
    assert 'href="/login?lang=en"' in chinese


def test_index_follows_browser_language(client, login_helper):
    login_helper(client, headers=ZH_BROWSER)
    chinese = client.get("/", headers=ZH_BROWSER).data.decode()
    assert "唤醒目标设备" in chinese
    english = client.get("/?lang=en", headers=ZH_BROWSER).data.decode()
    assert "Wake target device" in english


def test_manual_choice_is_cached_in_a_cookie(client):
    detected = client.get("/login", headers=ZH_BROWSER)
    assert "lang=" not in (detected.headers.get("Set-Cookie") or ""), "探测到的语言不该写 cookie"

    picked = client.get("/login?lang=zh-CN", headers=EN_BROWSER)
    assert "lang=zh-CN" in (picked.headers.get("Set-Cookie") or "")

    kept = client.get("/login", headers=EN_BROWSER)
    assert "用户名" in kept.data.decode(), "手动选择应当被记住并覆盖系统语言"

    switched = client.get("/login?lang=en", headers=ZH_BROWSER)
    assert "lang=en" in (switched.headers.get("Set-Cookie") or "")
    assert "Username" in client.get("/login", headers=ZH_BROWSER).data.decode()


def test_app_lang_applies_when_there_is_no_system_language(client, monkeypatch):
    monkeypatch.setenv("APP_LANG", "zh-CN")
    assert "用户名" in client.get("/login").data.decode()


def test_api_reports_the_resolved_language(auth_client, csrf, api):
    response = api(auth_client, csrf, {"mode": "key", "key": "enter"})
    assert response.get_json()["lang"] == "en"

    response = api(auth_client, csrf, {"mode": "key", "key": "enter"},
                   headers={"X-Lang": "zh-CN"})
    assert response.get_json()["lang"] == "zh-CN"
    assert response.get_json()["steps"] == ["按键 enter ×1"]


def test_error_messages_follow_the_request_language(auth_client, csrf, api):
    english = api(auth_client, csrf, {"mode": "key", "key": "nosuchkey"})
    assert "Unknown key" in english.get_json()["error"]

    chinese = api(auth_client, csrf, {"mode": "key", "key": "nosuchkey"},
                  headers={"X-Lang": "zh-CN"})
    assert "未知按键" in chinese.get_json()["error"]
