"""code_executor 旧调用兼容入口：宿主机代码执行已关闭。

在另有经过验证的独立隔离沙箱前，所有语言与调用方式均 fail-closed。
本模块不创建进程或临时执行文件，也不读取宿主环境用于执行。
"""

CODE_EXECUTOR_UNAVAILABLE = (
    "code_executor 不可用:宿主机代码执行已关闭,尚未提供独立隔离沙箱"
)


def code_executor(
    code: str,
    language: str = "python",
    timeout: int = 10,
) -> dict:
    """保持旧函数签名与返回结构，始终返回明确不可用结果。"""
    return {
        "stdout": "",
        "stderr": CODE_EXECUTOR_UNAVAILABLE,
        "exit_code": -6,
    }
