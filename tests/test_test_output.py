"""开发环境连接失败也不能把测试DSN密码写进pytest报告。"""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("malformed", [False, True])
def test_unavailable_database_does_not_echo_password(tmp_path, malformed):
    sentinel = "not-a-real-password-MUST-NOT-LEAK"
    xml = tmp_path / "connection-failure.xml"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_postgres.py::test_mode_mismatch_does_not_mutate_task",
         "-q", f"--junitxml={xml}"],
        env={**os.environ, "PYTHONUTF8": "1", "ANLAN_TEST_DATABASE_URL": sentinel if malformed
             else f"postgresql://synthetic:{sentinel}@127.0.0.1:1/nonexistent"},
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 1
    assert "连接详情已隐藏" in result.stdout
    assert sentinel not in result.stdout + result.stderr + xml.read_text(encoding="utf-8")
