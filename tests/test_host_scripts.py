"""Run the bash suites that cover the host-side scripts.

The host scripts are shell, so their tests are shell too; this wrapper makes a
plain `pytest` run cover everything.

宿主脚本是 shell 写的，因此它们的测试也是 shell；这个包装让一条 `pytest`
命令就能跑全部内容。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="需要 bash")
@pytest.mark.parametrize("script", ["host_scripts.sh", "host_i18n.sh"])
def test_host_suite(script):
    proc = subprocess.run(
        [BASH, str(HERE / script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
