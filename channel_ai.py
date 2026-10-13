# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""ایجنت‌های متن و تصویر مخصوص پست کانال (Jarvis + پشتیبان)، جدا از ایجنت‌های پشتیبانی و ادمین."""

import asyncio
import base64
import io
import json
import logging
import re

import aiohttp

import ai_support
import config

_log = logging.getLogger("channel_ai")

JARVIS_BASE_URL = "https://api.jarvis.you/v1"
JARVIS_TEXT_MODEL = "CLAUDE_6_5_HAIKU"
JARVIS_IMAGE_MODEL = "gemini-3-1-flash-image"
TEXT_MODES = ("auto", "jarvis", "shared")
IMAGE_MODES = ("auto", "jarvis", "gemini")
TEXT_MODE_LABELS = {
    "auto": "🤖 خودکار (اول Jarvis، بعد ایجنت‌های مشترک)",
    "jarvis": "🧠 فقط Jarvis",
    "shared": "🔁 فقط ایجنت‌های مشترک دستیار هوشمند",
}
IMAGE_MODE_LABELS = {
    "auto": "🤖 خودکار (اول Jarvis، بعد Gemini)",
    "jarvis": "🧠 فقط Jarvis",
    "gemini": "🔷 فقط Gemini",
}
IMAGE_STYLE = (
    "Premium 3D render, glossy glassmorphism and brushed-metal materials, one clear hero object as focal point, "
    "isometric cinematic composition, volumetric rim lighting, soft neon glow, floating particles, "
    "shallow depth of field, rich dark gradient background, ultra detailed, 16:9 wide. "
    "Absolutely no text, no letters, no numbers, no logos, no watermark, no people, no real brand names."
)
DEFAULT_IMAGE_PROMPT = "A glowing shield and a fast rocket over a futuristic network of light, symbolizing private fast internet"

_NON_TEXT = ("embed", "image", "tts", "whisper", "audio", "moderation", "rerank", "video")
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_TEXT_TIMEOUT = 300
_RETRY_SUFFIX = "\n\nپاسخ قبلی JSON معتبر نبود. فقط و فقط یک آبجکت JSON معتبر بده؛ بدون توضیح و بدون ```."
_gemini_image_cache = {}
_semaphore_obj = None


class ChannelAIError(Exception):
    """خطای ایجنت‌های متن/تصویر کانال با پیام قابل نمایش به ادمین."""


def _semaphore():
    global _semaphore_obj
    if _semaphore_obj is None:
        _semaphore_obj = asyncio.Semaphore(2)
    return _semaphore_obj
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍


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


def gemini_image_model(db) -> str:
    return ai_support._setting(db, "gemini_image_model", "auto") or "auto"


def text_mode(db) -> str:
    mode = ai_support._setting(db, "channel_text_provider", "auto")
    return mode if mode in TEXT_MODES else "auto"


def image_mode(db) -> str:
    mode = ai_support._setting(db, "channel_image_provider", "auto")
    return mode if mode in IMAGE_MODES else "auto"


def text_configured(db) -> bool:
    mode = text_mode(db)
    if mode in ("auto", "jarvis") and jarvis_keys(db):
        return True
    return mode in ("auto", "shared") and ai_support.is_configured(db)


def image_configured(db) -> bool:
    mode = image_mode(db)
    if mode in ("auto", "jarvis") and jarvis_keys(db):
        return True
    return mode in ("auto", "gemini") and bool(ai_support.resolve_gemini_keys(db))


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
    """(داده، منبع) از مدل متن کانال؛ بر اساس مسیر تنظیم‌شده Jarvis و/یا ایجنت‌های مشترک."""
    mode = text_mode(db)
    errors = []
    if mode in ("auto", "jarvis"):
        if jarvis_keys(db):
            try:
                return await _jarvis_json(db, system_prompt, user_text), f"jarvis/{jarvis_text_model(db)}"
            except Exception as exc:
                errors.append(_err(exc))
                _log.warning("channel text via jarvis failed: %s", _err(exc)[:200])
        else:
            errors.append("کلید Jarvis تنظیم نشده")
        if mode == "jarvis":
            raise ChannelAIError("؛ ".join(errors))
    if mode in ("auto", "shared") and await asyncio.to_thread(ai_support.is_configured, db):
        import ai_text
        try:
            return await ai_text.generate_json(db, system_prompt, user_text), "shared"
        except Exception as exc:
            errors.append(_err(exc))
    raise ChannelAIError("؛ ".join(errors) or "مدل متن کانال تنظیم نشده")


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


def _version_key(name: str) -> tuple:
    nums = re.findall(r"\d+(?:\.\d+)?", name)
    return (float(nums[0]) if nums else 0.0, "preview" not in name, "latest" not in name)


async def _gemini_image_model_pick(key: str, configured: str, force: bool = False) -> str:
    if configured not in ("", "auto") and not force:
        return configured
    if "m" in _gemini_image_cache and not force:
        return _gemini_image_cache["m"]
    data = await _request(
        "GET", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
        headers={"x-goog-api-key": key}, timeout=30,
    )
    names = []
    for item in data.get("models", []):
        name = str(item.get("name", "")).removeprefix("models/")
        if name.startswith("gemini") and "image" in name and "generateContent" in item.get("supportedGenerationMethods", []):
            names.append(name)
    pool = [n for n in names if "flash" in n] or names
    if not pool:
        raise ChannelAIError("مدل تصویر Gemini پیدا نشد")
    _gemini_image_cache["m"] = max(pool, key=_version_key)
    return _gemini_image_cache["m"]


async def _gemini_image(db, prompt: str) -> bytes:
    keys = ai_support.resolve_gemini_keys(db)
    if not keys:
        raise ChannelAIError("کلید Gemini تنظیم نشده")
    configured = gemini_image_model(db)
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["IMAGE"]}}
    last = None
    for key in keys:
        try:
            model = await _gemini_image_model_pick(key, configured)
            url = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
            try:
                data = await _request("POST", url.format(model), headers={"x-goog-api-key": key}, payload=payload, timeout=120)
            except ChannelAIError as exc:
                if "HTTP 404" not in str(exc) or configured not in ("", "auto"):
                    raise
                model = await _gemini_image_model_pick(key, configured, force=True)
                data = await _request("POST", url.format(model), headers={"x-goog-api-key": key}, payload=payload, timeout=120)
            for part in data["candidates"][0]["content"]["parts"]:
                blob = part.get("inlineData") or part.get("inline_data")
                if blob and blob.get("data"):
                    return base64.b64decode(blob["data"])
            raise ChannelAIError("پاسخ Gemini تصویر نداشت")
        except Exception as exc:
            last = exc
    raise ChannelAIError(f"gemini: {_err(last)}")


def _normalize(raw: bytes) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


async def generate_image(db, image_prompt: str) -> tuple:
    """(بایت JPEG، منبع) از مدل تصویر کانال؛ مستقل از مدل متن. اگر هیچ مسیری موفق نشد ChannelAIError."""
    mode = image_mode(db)
    prompt = f"{(image_prompt or DEFAULT_IMAGE_PROMPT).strip()}. {IMAGE_STYLE}"
    routes = []
    if mode in ("auto", "jarvis") and jarvis_keys(db):
        routes.append(("jarvis", f"jarvis/{jarvis_image_model(db)}", _jarvis_image))
    if mode in ("auto", "gemini") and ai_support.resolve_gemini_keys(db):
        routes.append(("gemini", "gemini", _gemini_image))
    if not routes:
        raise ChannelAIError("مدل تصویر کانال تنظیم نشده (کلید Jarvis یا Gemini لازم است)")
    errors = []
    for _name, label, fn in routes:
        try:
            raw = await fn(db, prompt)
            return await asyncio.to_thread(_normalize, raw), label
        except Exception as exc:
            errors.append(_err(exc))
            _log.warning("channel image via %s failed: %s", label, _err(exc)[:200])
    raise ChannelAIError("؛ ".join(errors))


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
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
