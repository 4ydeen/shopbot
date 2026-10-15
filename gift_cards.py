# -*- coding: utf-8 -*-
"""سرویس کارت هدیه: تنظیمات، ساخت تصویر کارت، ذخیره‌ی فایل‌ها و حلقه‌ی انقضا."""

import asyncio
import json
import logging
import os
import re
import uuid

import gift_card_render as gr
from jalali import to_jalali_str

_log = logging.getLogger("gift_cards")

DEFAULTS = {
    "gift_enabled": "1",
    "gift_allow_wallet": "1",
    "gift_allow_config": "1",
    "gift_allow_buy": "1",
    "gift_min_amount": "10000",
    "gift_max_amount": "5000000",
    "gift_fee_percent": "0",
    "gift_expire_days": "30",
    "gift_max_open": "5",
}
SETTING_LABELS = {
    "gift_enabled": "کارت هدیه فعال باشد",
    "gift_allow_wallet": "هدیه‌ی مبلغ کیف پول",
    "gift_allow_config": "هدیه‌ی کانفیگ",
    "gift_allow_buy": "خرید کانفیگ جدید به‌عنوان هدیه",
    "gift_min_amount": "حداقل مبلغ (تومان)",
    "gift_max_amount": "حداکثر مبلغ (تومان)",
    "gift_fee_percent": "کارمزد (درصد)",
    "gift_expire_days": "مدت اعتبار (روز)",
    "gift_max_open": "سقف کارت باز هر کاربر (۰ = نامحدود)",
}
BOOL_SETTINGS = ("gift_enabled", "gift_allow_wallet", "gift_allow_config", "gift_allow_buy")
STATUS_LABELS = {
    "active": "🟢 فعال", "disabled": "⏸ غیرفعال", "redeemed": "✅ استفاده‌شده",
    "expired": "⌛️ منقضی", "revoked": "🚫 باطل‌شده", "cancelled": "↩️ لغو توسط فرستنده",
}
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def setting(db, key: str) -> str:
    return str(db.get_setting(key, DEFAULTS[key]) or DEFAULTS[key])


def int_setting(db, key: str) -> int:
    try:
        return max(int(setting(db, key)), 0)
    except ValueError:
        return int(DEFAULTS[key])


def enabled(db, key: str = "gift_enabled") -> bool:
    return setting(db, "gift_enabled") == "1" and setting(db, key) == "1"


def money(value) -> str:
    return f"{int(value):,}".translate(_FA).replace(",", "٬")


def assets_dir(db, sub: str) -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(db.db_path)), "gift_assets", sub)
    os.makedirs(path, exist_ok=True)
    return path


def _write(db, sub: str, data: bytes, ext: str) -> str:
    path = os.path.join(assets_dir(db, sub), f"{uuid.uuid4().hex}.{ext}")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def _read(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def _remove(path):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        _log.warning("could not remove %s", path)


def deep_link(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start=gift_{re.sub('[^A-Za-z0-9]', '', code)}"


def theme_background(theme) -> bytes:
    raw = _read(theme["base_image_path"]) if theme["base_image_path"] else None
    return raw or gr.fallback_background(theme["color_a"], theme["color_b"])


def theme_layout(theme) -> dict:
    try:
        return gr.sanitize_layout(json.loads(theme["layout_json"])) if theme["layout_json"] else gr.DEFAULT_LAYOUT
    except (TypeError, ValueError):
        return gr.DEFAULT_LAYOUT


async def save_theme_image(db, theme_id: int, raw: bytes) -> dict:
    """عکس پایه‌ی تم را ذخیره و چیدمان متن را با AI تشخیص می‌دهد."""
    from PIL import Image
    import io

    Image.open(io.BytesIO(raw)).verify()
    theme = await asyncio.to_thread(db.gift_get_theme, theme_id)
    if not theme:
        raise ValueError("theme not found")
    old = theme["base_image_path"]
    path = await asyncio.to_thread(_write, db, "themes", raw, "png")
    layout = await gr.detect_layout(db, raw)
    await asyncio.to_thread(
        db.gift_update_theme, theme_id, base_image_path=path, layout_json=json.dumps(layout, ensure_ascii=False)
    )
    _remove(old)
    return layout


async def redetect_theme_layout(db, theme_id: int) -> dict:
    theme = await asyncio.to_thread(db.gift_get_theme, theme_id)
    raw = _read(theme["base_image_path"]) if theme and theme["base_image_path"] else None
    if not raw:
        raise ValueError("no base image")
    layout = await gr.detect_layout(db, raw)
    await asyncio.to_thread(db.gift_update_theme, theme_id, layout_json=json.dumps(layout, ensure_ascii=False))
    return layout


def card_content(card, code: str) -> dict:
    """متن‌های چاپی کارت. لینک اشتراک کانفیگ عمداً روی تصویر نمی‌آید؛ فقط بعد از دریافت تحویل داده می‌شود."""
    if card["kind"] == "wallet":
        info = [(f"{money(card['amount'])} تومان", 1.7), ("اعتبار کیف پول", 0.7)]
    else:
        snap = json.loads(card["config_snapshot"] or "{}")
        info = [(str(snap.get("name") or "کانفیگ"), 1.2)]
        volume = int(snap.get("volume_gb") or 0)
        days = int(snap.get("duration_days") or 0)
        info.append((f"{str(volume).translate(_FA)} گیگابایت" if volume else "حجم نامحدود", 0.9))
        info.append((f"{str(days).translate(_FA)} روز" if days else "زمان نامحدود", 0.9))
    until = to_jalali_str(card["expires_at"]).translate(_FA) if card["expires_at"] else ""
    code_lines = [(code, 1.0)]
    if until:
        code_lines.append((f"اعتبار تا {until}", 0.75))
    return {
        "recipient": card["recipient_name"], "message": card["message"],
        "info_lines": info, "code_lines": code_lines,
    }


async def build_card_image(db, card, code: str) -> str:
    """تصویر نهایی کارت را می‌سازد، ذخیره می‌کند و مسیرش را در کارت ثبت می‌کند."""
    theme = await asyncio.to_thread(db.gift_get_theme, card["theme_id"])
    if not theme:
        theme = (await asyncio.to_thread(db.gift_list_themes, False))[0]
    png = await asyncio.to_thread(
        gr.render_card, theme_background(theme), theme_layout(theme), card_content(card, code)
    )
    path = await asyncio.to_thread(_write, db, "cards", png, "png")
    await asyncio.to_thread(db.gift_set_image, card["id"], path)
    return path


def card_image_bytes(card):
    return _read(card["image_path"])


def delete_card_image(card):
    _remove(card["image_path"])


def delete_theme_image(theme):
    _remove(theme["base_image_path"])


async def expiry_loop(db, bot, interval: int = 600):
    """هر چند دقیقه کارت‌های سررسیدشده را برمی‌گرداند و فرستنده را مطلع می‌کند."""
    while True:
        try:
            released = await asyncio.to_thread(db.gift_expire_due)
            for card in released:
                what = f"{money(card['amount'])} تومان" if card["kind"] == "wallet" else "کانفیگ"
                try:
                    await bot.send_message(
                        card["sender_id"],
                        f"⌛️ کارت هدیه‌ی شما (به مقصد «{card['recipient_name'] or '-'}») منقضی شد و {what} به شما برگشت.",
                    )
                except Exception:
                    _log.info("expiry notice to %s failed", card["sender_id"])
        except Exception:
            _log.exception("gift expiry loop failed")
        await asyncio.sleep(interval)
