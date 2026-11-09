"""图形验证码:四位字符 + 干扰线/噪点,一次性、限时有效

- 使用 Pillow 生成 PNG,不依赖系统字体文件(Pillow 内置可缩放默认字体)
- 验证码只保存在进程内存,多实例部署时需由网关做会话粘滞或改用共享存储
- 校验使用常量时间比较,验证通过即从内存移除,防止重放
"""
import base64
import io
import random
import secrets
import threading
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core.config import settings

CAPTCHA_LENGTH = 4
CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CAPTCHA_MAX_ENTRIES = 5000

_store: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def captcha_required() -> bool:
    return bool(settings.CAPTCHA_ENABLED)


def _cleanup(now: float) -> None:
    expired = [key for key, (_, expires) in _store.items() if expires <= now]
    for key in expired:
        _store.pop(key, None)
    if len(_store) > CAPTCHA_MAX_ENTRIES:
        _store.clear()


def _render_image(code: str) -> str:
    width, height = 140, 48
    image = Image.new("RGB", (width, height), (245, 247, 250))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=34)

    # 干扰线
    for _ in range(4):
        draw.line(
            (
                random.randint(0, width), random.randint(0, height),
                random.randint(0, width), random.randint(0, height),
            ),
            fill=(
                random.randint(120, 190),
                random.randint(120, 190),
                random.randint(120, 190),
            ),
            width=1,
        )
    # 噪点
    for _ in range(120):
        draw.point(
            (random.randint(0, width), random.randint(0, height)),
            fill=(
                random.randint(90, 200),
                random.randint(90, 200),
                random.randint(90, 200),
            ),
        )

    x = 14
    for char in code:
        layer = Image.new("RGBA", (42, 46), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)
        layer_draw.text(
            (6, 0), char, font=font,
            fill=(
                random.randint(20, 90),
                random.randint(20, 90),
                random.randint(20, 90),
                255,
            ),
        )
        layer = layer.rotate(
            random.uniform(-24, 24), resample=Image.BICUBIC, expand=False,
        )
        image.paste(layer, (x, random.randint(0, 4)), layer)
        x += 30

    image = image.filter(ImageFilter.SMOOTH)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def generate_captcha() -> dict:
    """生成验证码:返回 ID、PNG Data URL 与有效期(不返回明文答案)"""
    code = "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(CAPTCHA_LENGTH))
    captcha_id = secrets.token_urlsafe(18)
    now = time.time()
    with _lock:
        _cleanup(now)
        _store[captcha_id] = (code, now + settings.CAPTCHA_TTL_SECONDS)
    return {
        "captcha_id": captcha_id,
        "image": _render_image(code),
        "expires_in": settings.CAPTCHA_TTL_SECONDS,
    }


def verify_captcha(captcha_id: str, code: str) -> bool:
    """校验并消费验证码;过期、错误或重复使用均返回 False"""
    if not captcha_id or not code:
        return False
    with _lock:
        item = _store.pop(captcha_id, None)
    if item is None:
        return False
    expected, expires = item
    if time.time() > expires:
        return False
    return secrets.compare_digest(expected, str(code).strip().upper())
