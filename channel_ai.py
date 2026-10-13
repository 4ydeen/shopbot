# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""ایجنت‌های متن و تصویر پست کانال. فقط از Jarvis استفاده می‌کند (دو مدل: یکی متن، یکی تصویر).

ایجنت‌های پشتیبانی، دستیار ادمین و بقیه‌ی بخش‌ها هیچ تأثیری روی این فایل ندارند."""

import asyncio
import base64
import io
import json
import logging
import os
import re
from datetime import datetime

import aiohttp

import ai_support
import config
import post_image

_log = logging.getLogger("channel_ai")

JARVIS_BASE_URL = "https://api.jarvis.you/v1"
JARVIS_TEXT_MODEL = "CLAUDE_6_5_HAIKU"
JARVIS_IMAGE_MODEL = "gemini-3-1-flash-image"
CHANNEL_LOGO_PATH = os.path.join(config.BASE_DIR, "channel_banner_logo.png")
LEARNING_KEY = "channel_ai_learning"
LEARNING_LIMIT = 40
LEARNING_IN_PROMPT = 8
COLORS_KEY = "channel_banner_colors"
DEFAULT_IMAGE_PROMPT = "A glowing shield and a fast rocket over a futuristic network of light, symbolizing private fast internet"
BANNER_RULES = (
    "Style: premium modern advertising banner, glossy gradients, soft glow, floating sparkles and subtle "
    "internet and security icons, strong contrast so every text is easy to read. "
    "All text must be in Persian (Farsi), right-to-left, spelled exactly as written in quotes, large bold readable font, "
    "no extra letters and no garbled characters. "
    "Keep every text element inside the central safe area with at least 10 percent margin from all edges. "
    "Do not add any other text: no English words, no watermark, no QR code, no real brand names, no logos, no human faces."
)

_NON_TEXT = ("embed", "image", "tts", "whisper", "audio", "moderation", "rerank", "video")
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_TEXT_TIMEOUT = 300
_RETRY_SUFFIX = "\n\nپاسخ قبلی JSON معتبر نبود. فقط و فقط یک آبجکت JSON معتبر بده؛ بدون توضیح و بدون ```."
_semaphore_obj = None


class ChannelAIError(Exception):
    """خطای ایجنت‌های متن/تصویر کانال با پیام قابل نمایش به ادمین."""


def _semaphore():
    global _semaphore_obj
    if _semaphore_obj is None:
        _semaphore_obj = asyncio.Semaphore(2)
    return _semaphore_obj


def _err(exc) -> str:
    return str(exc).strip() or type(exc).__name__


def is_text_model(model: str) -> bool:
    return bool(model) and not any(b in model.lower() for b in _NON_TEXT)


def jarvis_keys(db) -> list:
    keys = ai_support._split_keys(ai_support._setting(db, "jarvis_api_key"))
    return keys or ai_support._split_keys(getattr(config, "JARVIS_API_KEY", ""))


def jarvis_base(db) -> str:
    return ai_support.normalize_base_url(ai_support._setting(db, "jarvis_base_url")) or JARVIS_BASE_URL


def jarvis_text_model(db) -> str:
    model = ai_support._setting(db, "jarvis_text_model")
    return model if is_text_model(model) else JARVIS_TEXT_MODEL


def jarvis_image_model(db) -> str:
    return ai_support._setting(db, "jarvis_image_model") or JARVIS_IMAGE_MODEL


def jarvis_image_size(db) -> str:
    return ai_support._setting(db, "jarvis_image_size")


def text_configured(db) -> bool:
    return bool(jarvis_keys(db))


def image_configured(db) -> bool:
    return bool(jarvis_keys(db))


async def _request(method: str, url: str, headers: dict = None, payload: dict = None, timeout: int = 90, raw: bool = False):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout, connect=10)) as session:
        async with session.request(method, url, headers=headers or {}, json=payload) as resp:
            body = await resp.read()
            if resp.status >= 400:
                text = body.decode("utf-8", "ignore")
                if text.lstrip().lower().startswith(("<!doctype", "<html")):
                    raise ChannelAIError(f"HTTP {resp.status} (سرویس IP یا منطقه‌ی این سرور را بلاک کرده است)")
                raise ChannelAIError(f"HTTP {resp.status}: {text[:200]}")
            if raw:
                return body
            try:
                return json.loads(body)
            except ValueError as exc:
                raise ChannelAIError("پاسخ JSON نامعتبر") from exc


def _parse_json(text: str) -> dict:
    match = _JSON_RE.search(re.sub(r"```(?:json)?", "", text or ""))
    if not match:
        raise ChannelAIError("JSON در پاسخ مدل پیدا نشد")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ChannelAIError("ریشه‌ی JSON آبجکت نیست")
    return data


async def _jarvis_chat(db, system_prompt: str, user_text: str) -> str:
    keys = jarvis_keys(db)
    if not keys:
        raise ChannelAIError("کلید Jarvis تنظیم نشده")
    model = jarvis_text_model(db)
    payload = {"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]}
    last = None
    for key in keys:
        try:
            async with _semaphore():
                data = await _request(
                    "POST", f"{jarvis_base(db)}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"}, payload=payload, timeout=_TEXT_TIMEOUT,
                )
            return (data["choices"][0]["message"]["content"] or "").strip()
        except Exception as exc:
            last = exc
    raise ChannelAIError(f"jarvis/{model}: {_err(last)}")


async def _jarvis_json(db, system_prompt: str, user_text: str) -> dict:
    try:
        return _parse_json(await _jarvis_chat(db, system_prompt, user_text))
    except ChannelAIError as exc:
        if "JSON" not in str(exc):
            raise
    except ValueError:
        pass
    return _parse_json(await _jarvis_chat(db, system_prompt, user_text + _RETRY_SUFFIX))


async def ask_json(db, system_prompt: str, user_text: str) -> tuple:
    """(داده، منبع) از مدل متن Jarvis. فقط Jarvis؛ اگر کار نکرد خطای قابل نمایش می‌دهد."""
    if not jarvis_keys(db):
        raise ChannelAIError("کلید Jarvis تنظیم نشده")
    try:
        return await _jarvis_json(db, system_prompt, user_text), f"jarvis/{jarvis_text_model(db)}"
    except Exception as exc:
        _log.warning("channel text via jarvis failed: %s", _err(exc)[:200])
        raise ChannelAIError(_err(exc)) from exc


async def generate_json(db, system_prompt: str, user_text: str) -> dict:
    return (await ask_json(db, system_prompt, user_text))[0]


async def _jarvis_image(db, prompt: str) -> bytes:
    keys = jarvis_keys(db)
    if not keys:
        raise ChannelAIError("کلید Jarvis تنظیم نشده")
    model = jarvis_image_model(db)
    body = {"model": model, "prompt": prompt, "n": 1}
    size = jarvis_image_size(db)
    if size:
        body["size"] = size
    last = None
    for key in keys:
        for attempt in (1, 2):
            try:
                async with _semaphore():
                    data = await _request(
                        "POST", f"{jarvis_base(db)}/images/generations",
                        headers={"Authorization": f"Bearer {key}"}, payload=body, timeout=180,
                    )
                    item = (data.get("data") or [{}])[0]
                    if item.get("b64_json"):
                        return base64.b64decode(item["b64_json"])
                    if item.get("url"):
                        return await _request("GET", item["url"], timeout=60, raw=True)
                raise ChannelAIError("پاسخ تصویر نه b64_json داشت و نه url")
            except Exception as exc:
                last = exc
                if any(code in str(exc) for code in ("HTTP 401", "HTTP 402", "HTTP 403")) or attempt == 2:
                    break
                await asyncio.sleep(3)
    raise ChannelAIError(f"jarvis/{model}: {_err(last)}")


def _normalize(raw: bytes) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def build_banner_prompt(overlay: dict, scene: str = "", colors: str = "") -> str:
    """پرامپت بنر فارسی. متن‌ها عیناً داخل پرامپت می‌آیند تا مدل تصویر خودش آن‌ها را فارسی بکشد."""
    overlay = overlay or {}
    texts = []
    if overlay.get("title"):
        texts.append(f"headline «{overlay['title']}»")
    if overlay.get("price_toman"):
        texts.append(f"price «{post_image.fa_number(overlay['price_toman'])} تومان»")
    badge = post_image._badge_text(overlay)
    if badge:
        texts.append(f"discount badge «{badge}»")
    palette = (colors or "").strip()[:150] or "a modern harmonious palette that suits the scene"
    parts = [
        "Design a Persian advertising banner for a fast and private VPN internet service.",
        ("Persian texts to render exactly: " + "; ".join(texts) + ".") if texts else "",
        f"Brand colors requested by the admin: {palette}.",
        f"Scene and mood: {(scene or '').strip()[:300] or DEFAULT_IMAGE_PROMPT}.",
        BANNER_RULES,
    ]
    return " ".join(p for p in parts if p)


async def generate_image(db, prompt: str) -> tuple:
    """(بایت JPEG، منبع) از مدل تصویر Jarvis. prompt خالی یعنی بنر نمونه برای تست."""
    if not jarvis_keys(db):
        raise ChannelAIError("کلید Jarvis تنظیم نشده")
    prompt = (prompt or "").strip() or build_banner_prompt({"title": "پروکسی امن و سریع", "price_toman": 250000, "discount_percent": 20})
    try:
        raw = await _jarvis_image(db, prompt)
        return await asyncio.to_thread(_normalize, raw), f"jarvis/{jarvis_image_model(db)}"
    except Exception as exc:
        _log.warning("channel image via jarvis failed: %s", _err(exc)[:200])
        raise ChannelAIError(_err(exc)) from exc


def has_logo() -> bool:
    return os.path.isfile(CHANNEL_LOGO_PATH)


def save_logo(raw: bytes) -> None:
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as img:
        mark = img.convert("RGBA")
    mark.thumbnail((800, 800), Image.LANCZOS)
    mark.save(CHANNEL_LOGO_PATH, "PNG")


def remove_logo() -> bool:
    if os.path.isfile(CHANNEL_LOGO_PATH):
        os.remove(CHANNEL_LOGO_PATH)
        return True
    return False


def compose_banner(raw: bytes, size: str) -> bytes:
    """تصویر AI را به اندازه‌ی انتخابی می‌برد و لوگوی اختصاصی این بخش را بالا-راست می‌گذارد."""
    from PIL import Image
    jpeg = post_image.render(raw, None, size)
    if not has_logo():
        return jpeg
    base = Image.open(io.BytesIO(jpeg)).convert("RGBA")
    with Image.open(CHANNEL_LOGO_PATH) as logo_file:
        mark = logo_file.convert("RGBA")
    width, height = base.size
    mark.thumbnail((int(width * 0.22), int(height * 0.14)), Image.LANCZOS)
    margin = int(width * 0.05)
    base.alpha_composite(mark, (width - mark.width - margin, margin))
    out = io.BytesIO()
    base.convert("RGB").save(out, "JPEG", quality=92)
    return out.getvalue()


def saved_colors(db) -> str:
    return ai_support._setting(db, COLORS_KEY)


def save_colors(db, value: str) -> None:
    db.set_setting(COLORS_KEY, (value or "").strip()[:150])


def _load_learning(db) -> list:
    try:
        data = json.loads(db.get_setting(LEARNING_KEY, "[]") or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def learning_examples(db, limit: int = LEARNING_IN_PROMPT) -> list:
    """آخرین پست‌های تأییدشده (قدیمی به جدید)."""
    return _load_learning(db)[-limit:]


def record_approved(db, variant: dict, goal: str = "") -> None:
    """فقط وقتی ادمین پست را تأیید و به کانال فرستاد صدا زده می‌شود؛ پیش‌نویس و نسخه‌های ردشده یاد گرفته نمی‌شوند."""
    items = _load_learning(db)
    items.append({
        "angle": str(variant.get("angle") or "")[:80],
        "caption": str(variant.get("caption") or "")[:600],
        "button_text": str(variant.get("button_text") or "")[:64],
        "link_type": str((variant.get("deeplink") or {}).get("type") or "none"),
        "goal": (goal or "")[:200],
        "approved_at": datetime.now().isoformat(timespec="minutes"),
    })
    db.set_setting(LEARNING_KEY, json.dumps(items[-LEARNING_LIMIT:], ensure_ascii=False))


def clear_learning(db) -> None:
    db.set_setting(LEARNING_KEY, "[]")


async def list_jarvis_models(db) -> tuple:
    """(مدل‌های متنی، مدل‌های تصویری) از فهرست /models درگاه Jarvis."""
    keys = jarvis_keys(db)
    if not keys:
        return [], []
    data = await _request("GET", f"{jarvis_base(db)}/models", headers={"Authorization": f"Bearer {keys[0]}"}, timeout=20)
    ids = sorted({str(m.get("id", "")) for m in data.get("data", []) if m.get("id")})
    images = [i for i in ids if "image" in i.lower()]
    texts = [i for i in ids if not any(b in i.lower() for b in _NON_TEXT)]
    return texts, images


async def check_jarvis_key(base: str, key: str) -> tuple:
    """(معتبر؟، پیام). فقط 401/403 به‌معنی کلید نامعتبر است؛ خطای شبکه مانع ذخیره نمی‌شود."""
    try:
        await _request("GET", f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
        return True, ""
    except Exception as exc:
        text = _err(exc)
        return ("HTTP 401" not in text and "HTTP 403" not in text), text
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
