"""Keep the two READMEs in sync and check the documented conventions.

README.md is English and README.zh-CN.md is Chinese; both carry the language
switch line and the Licence section, and their section structure must match so
a translation cannot silently drift.

保持两版 README 同步，并检查文档约定。

README.md 为英文、README.zh-CN.md 为中文；两版都带语言切换行与许可段落，
且章节结构必须一致，避免翻译悄悄漏章节。
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SWITCH = "[English](README.md) | [简体中文](README.zh-CN.md)"
CJK = re.compile(r"[\u4e00-\u9fff]")

ENGLISH = (ROOT / "README.md").read_text(encoding="utf-8")
CHINESE = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("text", [ENGLISH, CHINESE])
def test_language_switch_is_the_third_line(text):
    assert text.splitlines()[2].strip() == SWITCH


@pytest.mark.parametrize("text,needle", [
    (ENGLISH, "## Language"),
    (ENGLISH, "## Verification checklist"),
    (ENGLISH, "## Known limitations"),
    (ENGLISH, "## Project layout"),
    (ENGLISH, "## Troubleshooting"),
    (ENGLISH, "## Testing"),
    (CHINESE, "## 语言"),
    (CHINESE, "## 验证清单"),
    (CHINESE, "## 已知限制"),
    (CHINESE, "## 项目结构"),
    (CHINESE, "## 排错"),
    (CHINESE, "## 测试"),
])
def test_expected_sections_exist(text, needle):
    assert needle in text


def test_section_counts_match():
    english = [ln for ln in ENGLISH.splitlines() if ln.startswith("## ")]
    chinese = [ln for ln in CHINESE.splitlines() if ln.startswith("## ")]
    assert len(english) == len(chinese), "%s vs %s" % (english, chinese)


def test_code_fences_are_balanced():
    for name, text in (("README.md", ENGLISH), ("README.zh-CN.md", CHINESE)):
        fences = [ln for ln in text.splitlines() if ln.startswith("```")]
        assert len(fences) % 2 == 0, "%s 的代码块没有配对" % name


def test_tables_have_consistent_columns():
    for name, text in (("README.md", ENGLISH), ("README.zh-CN.md", CHINESE)):
        block = []
        for line in text.splitlines() + [""]:
            if line.startswith("|"):
                block.append(line)
                continue
            if block:
                widths = {row.count("|") for row in block}
                assert len(widths) == 1, "%s 的表格列数不一致：%s" % (name, block[0])
                separator = block[1].replace("|", "").replace(" ", "")
                assert separator and set(separator) <= set("-:")
                block = []


def test_headings_do_not_skip_levels():
    for name, text in (("README.md", ENGLISH), ("README.zh-CN.md", CHINESE)):
        levels = [len(m.group(1)) for m in
                  (re.match(r"^(#{1,6}) ", ln) for ln in text.splitlines()) if m]
        jumps = [(a, b) for a, b in zip(levels, levels[1:]) if b > a + 1]
        assert not jumps, "%s 的标题层级跳级：%s" % (name, jumps)


def test_readmes_are_in_the_right_language():
    english_cjk = len(CJK.findall(ENGLISH))
    chinese_cjk = len(CJK.findall(CHINESE))
    # README.md 里只应出现界面文案引用等少量中文
    assert english_cjk < 400, "README.md 里中文过多：%d 字" % english_cjk
    assert chinese_cjk > 1000, "README.zh-CN.md 似乎不是中文：%d 字" % chinese_cjk


def test_licence_wording():
    assert "This project is licensed under the [MIT License](LICENSE)." in ENGLISH
    assert "本项目采用 [MIT License](LICENSE)。" in CHINESE
