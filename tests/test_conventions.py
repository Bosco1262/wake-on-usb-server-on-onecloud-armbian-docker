"""Enforce the repository's comment and docstring conventions.

Rule: explanatory comments and docstrings are bilingual, English first and
Chinese second, with a bare comment line between the two paragraphs of a
multi-line block. Bare section dividers are structural and exempt.

规则：说明性注释与 docstring 一律中英双语，英文在前、中文在后，多行时中间
用一行空注释符分隔。纯分隔线属于结构标记，不在要求之内。
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CJK = re.compile(r"[\u4e00-\u9fff]")
LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
DIVIDER = re.compile(r"^-{3,}.*-{3,}$")
COMMENTED_OUT_SETTING = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

SOURCE_FILES = [
    "app.py",
    "hid.py",
    "i18n.py",
    "Dockerfile",
    "docker-compose.yml",
    ".env.example",
    "host/i18n.sh",
    "host/setup-hid-gadget.sh",
    "host/teardown-hid-gadget.sh",
    "host/verify-hid.sh",
    "host/hid-gadget.service",
    "tests/conftest.py",
    "tests/helpers.py",
    "tests/test_app.py",
    "tests/test_hid.py",
    "tests/test_i18n.py",
    "tests/test_input_validation.py",
    "tests/test_conventions.py",
    "tests/test_docs.py",
    "tests/test_host_scripts.py",
    "tests/test_packaging.py",
]


def is_bilingual(text):
    return bool(CJK.search(text)) and bool(LATIN_WORD.search(text))


def comment_blocks(path):
    """Yield each run of consecutive # comments as a list of stripped bodies.

    把每一段连续的 # 注释作为一组剥离后的正文产出。
    """
    blocks = []
    current = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            body = stripped.lstrip("#").strip()
            if body and not COMMENTED_OUT_SETTING.match(body):
                current.append(body)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


@pytest.mark.parametrize("relative", SOURCE_FILES)
def test_explanatory_comments_are_bilingual(relative):
    path = ROOT / relative
    monolingual = []
    for block in comment_blocks(path):
        if all(DIVIDER.match(line) for line in block):
            continue
        joined = " ".join(block)
        if not is_bilingual(joined):
            monolingual.append(joined[:80])
    assert not monolingual, "以下注释只有一种语言：%s" % monolingual


@pytest.mark.parametrize("relative", [f for f in SOURCE_FILES if f.endswith(".py")])
def test_docstrings_are_bilingual(relative):
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    monolingual = []
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                count += 1
                if not is_bilingual(doc):
                    monolingual.append(getattr(node, "name", "<module>"))
    assert count > 0, "没有扫描到 docstring，检查解析逻辑"
    assert not monolingual, "以下 docstring 只有一种语言：%s" % monolingual
