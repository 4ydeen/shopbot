# -*- coding: utf-8 -*-
"""رندر کارت هدیه: چیدمان متن را AI از روی عکس پایه تشخیص می‌دهد و Pillow متن فارسی را دقیق روی آن چاپ می‌کند."""

import asyncio
import io
import json
import logging

from PIL import Image, ImageDraw, ImageFilter, ImageStat

import post_image as pi

_log = logging.getLogger("gift_card_render")

CARD_WIDTH = 1080
MIN_HEIGHT = 1080
MAX_HEIGHT = 1920
FIELDS = ("recipient", "message", "info", "code")

DEFAULT_LAYOUT = {
    "fields": {
        "recipient": {"x": 0.08, "y": 0.08, "w": 0.84, "h": 0.11, "align": "center"},
        "message": {"x": 0.10, "y": 0.26, "w": 0.80, "h": 0.26, "align": "center"},
        "info": {"x": 0.10, "y": 0.57, "w": 0.80, "h": 0.20, "align": "center"},
        "code": {"x": 0.10, "y": 0.83, "w": 0.80, "h": 0.10, "align": "center"},
    },
    "source": "default",
}

_LAYOUT_PROMPT = (
    "تو یک طراح کارت هدیه هستی. تصویر پایه‌ی یک کارت هدیه به تو داده می‌شود. "
    "چهار ناحیه‌ی مستطیلی برای چاپ متن روی آن پیدا کن که روی بخش‌های خلوت و کم‌جزئیات تصویر باشند "
    "و روی چهره، آرم، المان اصلی طرح یا لبه‌ها نیفتند و با هم همپوشانی نداشته باشند. "
    "نواحی: recipient (نام گیرنده، کوتاه)، message (متن پیام، بزرگ‌ترین ناحیه)، "
    "info (مبلغ یا مشخصات کانفیگ، ۲ تا ۴ خط)، code (کد هدیه و تاریخ انقضا، کوچک). "
    "مختصات نسبت به ابعاد تصویر و بین ۰ و ۱ باشد. فقط و فقط یک JSON با این ساختار برگردان: "
    '{"fields":{"recipient":{"x":0,"y":0,"w":0,"h":0,"align":"center"},"message":{...},"info":{...},"code":{...}}} '
    "که x و y گوشه‌ی بالا-چپ ناحیه و align یکی از right، center یا left است."
)


def _clamp(value, low, high):
    return max(low, min(high, value))


def sanitize_layout(raw) -> dict:
    """چیدمان خام را اعتبارسنجی می‌کند؛ در صورت نامعتبر بودن چیدمان پیش‌فرض برمی‌گردد."""
    try:
        fields = raw["fields"]
        clean = {}
        for name in FIELDS:
            box = fields[name]
            x = _clamp(float(box["x"]), 0.0, 0.9)
            y = _clamp(float(box["y"]), 0.0, 0.95)
            w = _clamp(float(box["w"]), 0.12, 1.0 - x)
            h = _clamp(float(box["h"]), 0.04, 1.0 - y)
            align = box.get("align") if box.get("align") in ("right", "center", "left") else "center"
            clean[name] = {"x": x, "y": y, "w": w, "h": h, "align": align}
    except (KeyError, TypeError, ValueError, AttributeError):
        return json.loads(json.dumps(DEFAULT_LAYOUT))
    if _overlap_ratio(clean) > 0.25:
        return json.loads(json.dumps(DEFAULT_LAYOUT))
    return {"fields": clean, "source": "ai"}


def _overlap_ratio(fields: dict) -> float:
    names = list(fields)
    worst = 0.0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            fa, fb = fields[a], fields[b]
            ix = max(0.0, min(fa["x"] + fa["w"], fb["x"] + fb["w"]) - max(fa["x"], fb["x"]))
            iy = max(0.0, min(fa["y"] + fa["h"], fb["y"] + fb["h"]) - max(fa["y"], fb["y"]))
            smaller = min(fa["w"] * fa["h"], fb["w"] * fb["h"])
            worst = max(worst, (ix * iy) / smaller if smaller else 1.0)
    return worst


async def detect_layout(db, image_bytes: bytes) -> dict:
    """از Gemini می‌خواهد جای مناسب متن‌ها را روی عکس پیدا کند؛ در خطا چیدمان پیش‌فرض."""
    import ai_support
    import ai_text

    keys = ai_support.resolve_gemini_keys(db)
    if not keys:
        return json.loads(json.dumps(DEFAULT_LAYOUT))
    from google.genai import types

    thumb = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    thumb.thumbnail((1024, 1024))
    buf = io.BytesIO()
    thumb.save(buf, "JPEG", quality=85)
    contents = [types.Content(role="user", parts=[
        types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
        types.Part(text=_LAYOUT_PROMPT),
    ])]
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
    model = ai_support.resolve_gemini_model(db)
    for api_key in keys:
        client = ai_support._build_client(api_key)
        try:
            response = await asyncio.to_thread(
                client.models.generate_content, model=model, contents=contents, config=config,
            )
            return sanitize_layout(ai_text.parse_json_object(response.text or ""))
        except Exception as exc:
            _log.warning("gift layout detection failed: %s", exc)
            if not ai_support._is_retryable(exc):
                break
    return json.loads(json.dumps(DEFAULT_LAYOUT))


def fallback_background(color_a: str, color_b: str, height: int = 1440) -> bytes:
    """پس‌زمینه‌ی گرادیانی برای تمی که هنوز عکس پایه ندارد."""
    a, b = pi._rgb(color_a, "#7C3AED"), pi._rgb(color_b, "#EC4899")
    ramp = Image.linear_gradient("L").resize((CARD_WIDTH, height))
    channels = [ramp.point(lambda v, lo=a[i], hi=b[i]: int(lo + (hi - lo) * v / 255)) for i in range(3)]
    out = io.BytesIO()
    Image.merge("RGB", channels).save(out, "PNG")
    return out.getvalue()


def _prepare_base(base_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(base_bytes)).convert("RGB")
    scale = CARD_WIDTH / img.width
    height = _clamp(int(img.height * scale), MIN_HEIGHT, MAX_HEIGHT)
    return pi._cover(img, (CARD_WIDTH, height))


def _region_style(base: Image.Image, box: tuple):
    region = base.crop(box)
    stat = ImageStat.Stat(region.convert("L"))
    luminance = stat.mean[0] / 255.0
    busy = stat.stddev[0] > 30
    ink = (24, 24, 28) if luminance > 0.58 else (255, 255, 255)
    return ink, busy


def _fit(draw, lines: list, width: float, height: float, start: int, minimum: int = 20):
    size = int(start)
    while True:
        font = pi._font(size)
        wrapped = []
        for text, weight in lines:
            wrapped += [(row, weight) for row in pi._wrap(draw, text, font, width / weight)] or []
        total = sum(int(size * weight * 1.45) for _, weight in wrapped)
        widest = max((pi._width(draw, row, pi._font(int(size * w))) for row, w in wrapped), default=0)
        if (total <= height and widest <= width) or size <= minimum:
            return size, wrapped
        size -= 2


def _has_rtl(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def _draw_field(canvas: Image.Image, spec: dict, lines: list):
    if not lines:
        return
    width, height = canvas.size
    box = (int(spec["x"] * width), int(spec["y"] * height), int((spec["x"] + spec["w"]) * width), int((spec["y"] + spec["h"]) * height))
    bw, bh = box[2] - box[0], box[3] - box[1]
    ink, busy = _region_style(canvas.convert("RGB"), box)
    if busy:
        plate = Image.new("RGBA", (bw + 40, bh + 24), (0, 0, 0, 0))
        fill = (255, 255, 255, 120) if ink[0] < 128 else (0, 0, 0, 120)
        ImageDraw.Draw(plate).rounded_rectangle((0, 0, plate.width - 1, plate.height - 1), radius=28, fill=fill)
        plate = plate.filter(ImageFilter.GaussianBlur(2))
        canvas.alpha_composite(plate, (box[0] - 20, box[1] - 12))
    draw = ImageDraw.Draw(canvas)
    base_size = min(bh * 0.5, bw * 0.12)
    size, rows = _fit(draw, lines, bw - 8, bh, base_size)
    step_total = sum(int(size * w * 1.45) for _, w in rows)
    y = box[1] + max((bh - step_total) // 2, 0)
    for text, weight in rows:
        font = pi._font(int(size * weight))
        if spec["align"] == "right":
            anchor, x = "ra", box[2]
        elif spec["align"] == "left":
            anchor, x = "la", box[0]
        else:
            anchor, x = "ma", (box[0] + box[2]) / 2
        rtl = _has_rtl(text)
        shown = pi._display(text) if rtl else text
        kwargs = pi._text_kwargs() if rtl else {}
        draw.text((x, y), shown, font=font, fill=ink, anchor=anchor, **kwargs)
        y += int(size * weight * 1.45)


def render_card(base_bytes: bytes, layout: dict, content: dict) -> bytes:
    """content: recipient, message، info_lines [(متن، وزن فونت)]، code_lines [(متن، وزن)] ← PNG."""
    if not pi.engine_status():
        raise pi.PostImageError("برای نوشتن فارسی روی کارت باید arabic-reshaper و python-bidi نصب باشند.")
    layout = layout if layout and "fields" in layout else DEFAULT_LAYOUT
    canvas = _prepare_base(base_bytes).convert("RGBA")
    fields = layout["fields"]
    recipient = (content.get("recipient") or "").strip()
    message = (content.get("message") or "").strip()
    _draw_field(canvas, fields["recipient"], [(f"برای {recipient}", 1.0)] if recipient else [])
    _draw_field(canvas, fields["message"], [(message, 1.0)] if message else [])
    _draw_field(canvas, fields["info"], content.get("info_lines") or [])
    _draw_field(canvas, fields["code"], content.get("code_lines") or [])
    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()
