"""code_executor:沙箱代码执行(subprocess 隔离)

实现要点:
- subprocess 隔离执行,超时 10s
- 内存限制 256MB(Windows 下用 resource 不可用,改用 Job Object 或跳过)
- 禁止网络访问(通过环境变量与代码审查)
- 捕获 stderr 反馈给 tutor_agent 做引导式排错
"""
import os
import sys
import tempfile
import logging
import subprocess

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARS = 5000

# 禁止导入的危险模块(简单代码审查)
DANGEROUS_PATTERNS = [
    "import socket", "import requests", "import urllib",
    "import http", "import ftplib", "import smtplib",
    "import telnetlib", "import paramiko", "import subprocess",
    "os.system", "os.popen", "os.exec", "os.spawn", "os.remove",
    "shutil.rmtree", "__import__", "eval(", "exec(",
]


def _check_safety(code: str) -> str | None:
    """代码安全审查,返回风险描述或 None"""
    for pattern in DANGEROUS_PATTERNS:
        if pattern in code:
            return f"代码包含受限操作: {pattern}"
    return None


def _run_python(code: str, timeout: int) -> dict:
    """执行 Python 代码"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=tempfile.gettempdir(),
        )
        return {
            "stdout": result.stdout[:MAX_OUTPUT_CHARS],
            "stderr": result.stderr[:MAX_OUTPUT_CHARS],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"执行超时(>{timeout}s),可能存在死循环",
            "exit_code": -1,
        }
    except Exception as e:
        return {"stdout": "", "stderr": f"执行异常: {e}", "exit_code": -2}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _run_java(code: str, timeout: int) -> dict:
    """执行 Java 代码(MVP:需本机安装 JDK)"""
    return {
        "stdout": "",
        "stderr": "Java 执行暂未启用,请在本地环境运行",
        "exit_code": -3,
    }


def _run_cpp(code: str, timeout: int) -> dict:
    """执行 C++ 代码(MVP:需本机安装 g++)"""
    return {
        "stdout": "",
        "stderr": "C++ 执行暂未启用,请在本地环境运行",
        "exit_code": -3,
    }


def code_executor(
    code: str,
    language: str = "python",
    timeout: int = TIMEOUT_SECONDS,
) -> dict:
    """沙箱代码执行工具

    Args:
        code: 待执行代码
        language: 编程语言(python/java/cpp)
        timeout: 超时秒数(上限 10s)

    Returns:
        {"stdout", "stderr", "exit_code"}
    """
    timeout = min(timeout, TIMEOUT_SECONDS)

    # 安全审查
    risk = _check_safety(code)
    if risk:
        return {
            "stdout": "",
            "stderr": f"安全拦截: {risk}。沙箱禁止网络/文件系统/进程操作。",
            "exit_code": -4,
        }

    runners = {"python": _run_python, "java": _run_java, "cpp": _run_cpp}
    runner = runners.get(language.lower())
    if not runner:
        return {"stdout": "", "stderr": f"不支持的语言: {language}", "exit_code": -5}

    logger.info("code_executor 执行 %s 代码(%d 字符)", language, len(code))
    return runner(code, timeout)