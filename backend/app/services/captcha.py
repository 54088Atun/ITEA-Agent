"""图形验证码:四位字符 + 干扰线/噪点,一次性、限时有效

- 使用 Pillow 生成 PNG,不依赖系统字体文件(Pillow 内置可缩放默认字体)
- 默认保存在进程内存;设置 CAPTCHA_STORE=file 后写入共享目录,
  多进程/多实例(共享同一磁盘)可跨进程校验
- 校验使用常量时间比较,验证通过即删除,防止重放
"""
import base64
import hashlib
import io
import os
import random
import secrets
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core.config import settings

CAPTCHA_LENGTH = 4
CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CAPTCHA_MAX_ENTRIES = 5000
CLEANUP_INTERVAL = 64

_store: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()
_generate_count = 0


def captcha_required() -> bool:
    return bool(settings.CAPTCHA_ENABLED)


def _file_dir() -> Path | None:
    """file 模式返回共享目录,其余模式返回 None(使用内存)"""
    mode = (settings.CAPTCHA_STORE or "memory").strip().lower()
    directory = (settings.CAPTCHA_STORE_DIR or "").strip()
    if mode != "file" or not directory:
        return None
    return Path(directory)


def _entry_path(captcha_id: str) -> Path:
    """用哈希做文件名,避免外部传入的 ID 造成路径穿越"""
    digest = hashlib.sha256(captcha_id.encode("utf-8")).hexdigest()
    return _file_dir() / digest


def _write_entry(captcha_id: str, code: str, expires: float) -> None:
    target = _entry_path(captcha_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".{secrets.token_hex(4)}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{code}\n{int(expires)}")
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _read_and_consume(captcha_id: str) -> tuple[str, float] | None:
    """读取后立即删除;删除失败说明已被其他进程消费"""
    target = _entry_path(captcha_id)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        target.unlink()
    except OSError:
        return None
    parts = raw.splitlines()
    if len(parts) < 2:
        return None
    try:
        return parts[0], float(parts[1])
    except ValueError:
        return None


def _maybe_cleanup_files(directory: Path, now: float) -> None:
    global _generate_count
    with _lock:
        _generate_count += 1
        if _generate_count % CLEANUP_INTERVAL != 0:
            return
    cutoff = now - (settings.CAPTCHA_TTL_SECONDS + 60)
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for item in entries:
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink()
        except OSError:
            continue


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
    expires = now + settings.CAPTCHA_TTL_SECONDS
    store_dir = _file_dir()
    if store_dir is None:
        with _lock:
            _cleanup(now)
            _store[captcha_id] = (code, expires)
    else:
        _write_entry(captcha_id, code, expires)
        _maybe_cleanup_files(store_dir, now)
    return {
        "captcha_id": captcha_id,
        "image": _render_image(code),
        "expires_in": settings.CAPTCHA_TTL_SECONDS,
    }


def verify_captcha(captcha_id: str, code: str) -> bool:
    """校验并消费验证码;过期、错误或重复使用均返回 False"""
    if not captcha_id or not code:
        return False
    if _file_dir() is None:
        with _lock:
            item = _store.pop(captcha_id, None)
    else:
        item = _read_and_consume(captcha_id)
    if item is None:
        return False
    expected, expires = item
    if time.time() > expires:
        return False
    return secrets.compare_digest(expected, str(code).strip().upper())
