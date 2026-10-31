"""提示词模板加载器"""
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """加载提示词模板,name 不含扩展名,如 load_prompt("router")"""
    path = PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, **kwargs) -> str:
    """安全渲染模板:用 str.replace 替换 {key} 占位符,不解析其他花括号

    与 str.format 不同,模板中的 JSON 示例花括号不会被误解析为占位符。
    """
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", str(value))
    return template