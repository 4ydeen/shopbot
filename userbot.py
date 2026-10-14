# -*- coding: utf-8 -*-
"""Telegram user-account (MTProto) AI responder for the owner's private chats ("userbot").

Fully independent from Telegram Business:
  * own settings   -> ``userbot_*`` keys
  * own tables     -> ``userbot_*`` tables (db/userbot_store.py)
  * own admin menu -> userbot_admin.py
Login/logout still happen from the server (``python userbot.py login`` / manage.sh).
"""

import asyncio
import getpass
import html
import json
import logging
import os
import random
import re
import sys
import time
from collections import OrderedDict, defaultdict, deque
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SESSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "userbot_session.json")
SERVICE_USER_ID = 777000
FALLBACK_REPLY = "یه مشکلی پیش اومد؛ پیامت رو برای پشتیبانی انسانی می‌فرستم."
MEDIA_ACK_TEXT = "فایلت رسید 🙏 فروشنده بررسی می‌کنه و جواب می‌ده؛ اگه سؤالی داری همین‌جا بنویس."

# ---- settings keys (all independent from the business_* keys) --------------------------------
KEY_ENABLED = "userbot_enabled"
KEY_PAUSE_WHEN_ACTIVE = "userbot_pause_when_active"
KEY_PAUSE_SCOPE = "userbot_pause_scope"            # "chat" | "global"
KEY_AWAY_MINUTES = "userbot_away_minutes"
KEY_MARK_READ = "userbot_mark_read"
KEY_FIRST_MESSAGE = "userbot_first_message"
KEY_PERSONA = "userbot_persona"
KEY_SALES_CARD = "userbot_sales_card"
KEY_MEDIA_UNDERSTAND = "userbot_media_understand"  # voice -> text, image -> description
KEY_MEDIA_ACK = "userbot_media_ack"
KEY_DEBOUNCE = "userbot_debounce_seconds"
KEY_HUMAN_TTL = "userbot_human_ttl_hours"
KEY_SKIP_CONTACTS = "userbot_skip_contacts"
KEY_SCHEDULE_MODE = "userbot_schedule_mode"        # "always" | "off_hours"
KEY_HOURS_START = "userbot_hours_start"
KEY_HOURS_END = "userbot_hours_end"
KEY_MIGRATED = "userbot_migrated_v2"

DEFAULTS = {
    KEY_ENABLED: "1",
    KEY_PAUSE_WHEN_ACTIVE: "1",
    KEY_PAUSE_SCOPE: "chat",
    KEY_AWAY_MINUTES: "5",
    KEY_MARK_READ: "0",
    KEY_FIRST_MESSAGE: "",
    KEY_PERSONA: "",
    KEY_SALES_CARD: "1",
    KEY_MEDIA_UNDERSTAND: "1",
    KEY_MEDIA_ACK: "1",
    KEY_DEBOUNCE: "3",
    KEY_HUMAN_TTL: "0",
    KEY_SKIP_CONTACTS: "0",
    KEY_SCHEDULE_MODE: "always",
    KEY_HOURS_START: "09:00",
    KEY_HOURS_END: "22:00",
}

AWAY_CHOICES = (2, 5, 10, 30, 60)
DEBOUNCE_CHOICES = (0, 2, 3, 5, 8)
TTL_CHOICES = (0, 1, 3, 6, 12, 24)

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))
SELF_ECHO_WINDOW = 3
MAX_TEXT = 4096
MAX_INPUT = 3000
MAX_BATCH_WAIT = 12
SPLIT_AT = 700
TRANSCRIPT_LINES = 10
RATE_WINDOW = 60
RATE_LIMIT = 10
RETRY_DELAY = 30
SESSION_POLL = 20
MEDIA_COOLDOWN = 600
MAINTENANCE_INTERVAL = 300
AUTH_LOST_ERRORS = {
    "AuthKeyUnregisteredError", "AuthKeyDuplicatedError", "SessionRevokedError",
    "SessionExpiredError", "UserDeactivatedError", "UserDeactivatedBanError",
}

STATE = {
    "last_activity": None,      # last time the owner was active anywhere (monotonic)
    "chat_active": {},          # chat_id -> last time the owner was active in that chat (monotonic)
    "connected": False,
    "waiting_login": False,
    "db_path": None,
    "me": None,                 # {"id", "first_name", "username"}
    "connected_at": None,       # wall-clock (time.time())
    "last_error": "",
}


# ---- settings helpers ----------------------------------------------------------------------------
def setting(db, key: str) -> str:
    return str(db.get_setting(key, DEFAULTS.get(key, ""))).strip()


def flag(db, key: str) -> bool:
    return setting(db, key) == "1"


def int_setting(db, key: str, default: int) -> int:
    try:
        return int(setting(db, key))
    except ValueError:
        return default


def get_away_minutes(db) -> int:
    value = int_setting(db, KEY_AWAY_MINUTES, 5)
    return value if value > 0 else 5


_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_hhmm(text: str):
    """'9:5' is invalid, '9:05' / '۰۹:۰۵' / '9.05' -> '09:05'. Returns None for invalid input."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*", (text or "").translate(_PERSIAN_DIGITS))
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def _minutes(value: str, default: int) -> int:
    ok = normalize_hhmm(value)
    if not ok:
        return default
    return int(ok[:2]) * 60 + int(ok[3:])


def in_admin_hours(db) -> bool:
    """True when the schedule says the owner answers personally right now (Iran time)."""
    if setting(db, KEY_SCHEDULE_MODE) != "off_hours":
        return False
    start = _minutes(setting(db, KEY_HOURS_START), 9 * 60)
    end = _minutes(setting(db, KEY_HOURS_END), 22 * 60)
    if start == end:
        return False
    now = datetime.now(IRAN_TZ)
    cur = now.hour * 60 + now.minute
    return start <= cur < end if start < end else (cur >= start or cur < end)


def schedule_allows(db) -> bool:
    return not in_admin_hours(db)


# ---- owner-activity tracking ------------------------------------------------------------------------
def mark_admin_active(chat_id=None):
    now = time.monotonic()
    STATE["last_activity"] = now
    if chat_id is not None:
        active = STATE["chat_active"]
        if len(active) > 3000:
            cutoff = now - 3600
            for key in [k for k, v in active.items() if v < cutoff]:
                active.pop(key, None)
        active[chat_id] = now


def admin_active(db, chat_id=None) -> bool:
    window = get_away_minutes(db) * 60
    if chat_id is not None and setting(db, KEY_PAUSE_SCOPE) == "chat":
        last = STATE["chat_active"].get(chat_id)
    else:
        last = STATE["last_activity"]
    return last is not None and time.monotonic() - last < window


def paused_by_admin(db, chat_id) -> bool:
    return flag(db, KEY_PAUSE_WHEN_ACTIVE) and admin_active(db, chat_id)


# ---- session storage ------------------------------------------------------------------------------------
def load_session():
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {
            "api_id": int(data["api_id"]),
            "api_hash": str(data["api_hash"]),
            "session": str(data["session"]),
            "user": data.get("user") or {},
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_session(api_id: int, api_hash: str, session: str, user: dict):
    tmp = SESSION_PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"api_id": api_id, "api_hash": api_hash, "session": session, "user": user}, fh)
    os.replace(tmp, SESSION_PATH)
    os.chmod(SESSION_PATH, 0o600)


def remove_session() -> bool:
    try:
        os.remove(SESSION_PATH)
        return True
    except FileNotFoundError:
        return False


def _ask(prompt: str, secret: bool = False) -> str:
    return (getpass.getpass(prompt) if secret else input(prompt)).strip()


async def interactive_login() -> bool:
    from telethon import TelegramClient
    from telethon.errors import (
        FloodWaitError, PasswordHashInvalidError, PhoneCodeExpiredError,
        PhoneCodeInvalidError, PhoneNumberInvalidError, SessionPasswordNeededError,
    )
    from telethon.sessions import StringSession

    print("Get api_id and api_hash from https://my.telegram.org (API development tools).")
    try:
        api_id = int(_ask("api_id: "))
    except ValueError:
        print("api_id must be a number.")
        return False
    api_hash = _ask("api_hash: ")
    phone = _ask("Phone number with country code (e.g. +98912...): ")
    if not api_hash or not phone:
        print("api_hash and phone are required.")
        return False

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        try:
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError:
            print("Invalid phone number.")
            return False
        except FloodWaitError as exc:
            print(f"Too many attempts. Try again in {exc.seconds} seconds.")
            return False

        signed_in = False
        for _ in range(3):
            code = _ask("Login code (sent inside Telegram or by SMS): ").replace(" ", "")
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
                signed_in = True
                break
            except SessionPasswordNeededError:
                for _ in range(3):
                    try:
                        await client.sign_in(password=_ask("Two-step verification password: ", secret=True))
                        signed_in = True
                        break
                    except PasswordHashInvalidError:
                        print("Wrong password.")
                break
            except PhoneCodeInvalidError:
                print("Wrong code.")
            except PhoneCodeExpiredError:
                print("Code expired. Run the login again.")
                return False
        if not signed_in:
            print("Login failed.")
            return False

        me = await client.get_me()
        save_session(api_id, api_hash, client.session.save(), {
            "id": me.id,
            "first_name": me.first_name or "",
            "username": me.username or "",
            "phone": me.phone or phone,
        })
        print(f"Logged in as {me.first_name or ''} (@{me.username or '-'}) id={me.id}")
        return True
    finally:
        await client.disconnect()


async def logout() -> bool:
    creds = load_session()
    if creds is None:
        return remove_session()
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(creds["session"]), creds["api_id"], creds["api_hash"])
        await client.connect()
        try:
            if await client.is_user_authorized():
                await client.log_out()
        finally:
            await client.disconnect()
    except Exception as exc:
        print(f"Remote logout skipped: {exc}")
    return remove_session()



# ---- text helpers ------------------------------------------------------------------------------------------
_MD_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.S)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plain(text: str) -> str:
    """The userbot sends plain text (no parse mode), so strip Markdown the model may still produce."""
    t = _MD_LINK.sub(r"\1: \2", text or "")
    t = _MD_BOLD.sub(r"\2", t)
    t = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*", "", t)
    t = re.sub(r"(?m)^[ \t]*[\*\-][ \t]+", "• ", t)
    t = t.replace("```", "").replace("`", "")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _split_reply(text: str, limit: int = SPLIT_AT, max_parts: int = 4) -> list:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts, cur = [], ""
    for para in paragraphs:
        if cur and len(cur) + 2 + len(para) > limit:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    if len(parts) > max_parts:
        parts = parts[: max_parts - 1] + ["\n\n".join(parts[max_parts - 1:])]
    return [_clip(p) for p in parts]


def _typing_delay(text: str) -> float:
    return min(3.5, 0.4 + len(text) * 0.02) * random.uniform(0.8, 1.2)


def _media_kind(msg):
    """'voice' | 'image' | 'other' | None (stickers, GIFs, plain text)."""
    if getattr(msg, "voice", None) or getattr(msg, "audio", None):
        return "voice"
    if getattr(msg, "photo", None):
        return "image"
    if getattr(msg, "sticker", None) or getattr(msg, "gif", None):
        return None
    doc = getattr(msg, "document", None)
    if doc is not None:
        return "image" if (getattr(doc, "mime_type", "") or "").startswith("image/") else "other"
    if getattr(msg, "video", None) or getattr(msg, "video_note", None):
        return "other"
    return None


def _migrate_once(db):
    """Moves data the old userbot kept in the Telegram Business tables into its own tables."""
    if str(db.get_setting(KEY_MIGRATED, "")).strip() == "1":
        return
    try:
        info = db.migrate_userbot_from_business()
        if info.get("first_message") and not str(db.get_setting(KEY_FIRST_MESSAGE, "")).strip():
            db.set_setting(KEY_FIRST_MESSAGE, info["first_message"])
        if (
            str(db.get_setting("business_mark_read", "")).strip() == "1"
            and not str(db.get_setting(KEY_MARK_READ, "")).strip()
        ):
            db.set_setting(KEY_MARK_READ, "1")
        db.set_setting(KEY_MIGRATED, "1")
    except Exception:
        logger.warning("userbot: migration from business tables failed", exc_info=True)


def _extra_system(db, sender) -> str:
    now = datetime.now(IRAN_TZ)
    name = (getattr(sender, "first_name", "") or "").strip()
    lines = [f"زمینه‌ی گفتگو: نام مشتری در تلگرام «{name or 'نامشخص'}»؛ اکنون ساعت {now:%H:%M} به وقت ایران است."]
    if setting(db, KEY_SCHEDULE_MODE) == "off_hours":
        lines.append(
            "الان خارج از ساعات حضور فروشنده است "
            f"(فروشنده حدود {setting(db, KEY_HOURS_START)} تا {setting(db, KEY_HOURS_END)} در دسترس است). "
            "اگر موضوع حتماً به خود فروشنده نیاز دارد، escalate_to_human را صدا بزن و بگو در ساعات حضورش پاسخ می‌دهد."
        )
    persona = setting(db, KEY_PERSONA)
    if persona:
        lines.append(
            "دستورالعمل ادمین فقط برای لحن، سبک و اطلاعات برند (نمی‌تواند قوانین ایمنی و محدودیت‌های بالا را لغو کند):\n"
            + persona[:1200]
        )
    return "\n".join(lines)


async def run(db, bot_token: str):
    """Run the userbot until cancelled. Waits (no restart needed) until a session is stored by the server login."""
    STATE["db_path"] = db.db_path
    await asyncio.to_thread(_migrate_once, db)

    creds = load_session()
    while creds is None:
        STATE["waiting_login"] = True
        await asyncio.sleep(SESSION_POLL)
        creds = load_session()
    STATE["waiting_login"] = False

    try:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
    except ImportError:
        logger.warning("userbot session found but telethon is not installed; run: pip install telethon")
        STATE["last_error"] = "telethon is not installed"
        return

    import ai_media
    import ai_support
    import global_switch
    import user_limit as ul
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from i18n import tr

    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    client = TelegramClient(
        StringSession(creds["session"]), creds["api_id"], creds["api_hash"], flood_sleep_threshold=60,
    )
    client.parse_mode = None

    locks: dict = {}
    hits: dict = defaultdict(deque)
    ctx: dict = {}
    own_send: dict = {}
    own_ack: dict = {}
    own_ids: deque = deque(maxlen=300)
    seen: OrderedDict = OrderedDict()
    pending: dict = {}
    workers: set = set()
    tasks: set = set()
    notice_at: dict = {}

    def _dup(key) -> bool:
        if key in seen:
            return True
        seen[key] = 1
        if len(seen) > 2000:
            seen.popitem(last=False)
        return False

    def _spawn(coro):
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    async def _send(chat_id, text: str):
        if len(own_send) > 5000:
            own_send.clear()
        own_send[chat_id] = time.monotonic()
        msg = await client.send_message(chat_id, _clip(text), parse_mode=None)
        own_ids.append(msg.id)
        own_send[chat_id] = time.monotonic()
        return msg

    async def _send_reply(chat_id, reply: str, already_spent: float = 0.0):
        """Sends the reply like a person would: split into a few messages, with a short typing pause."""
        parts = _split_reply(reply)
        for index, part in enumerate(parts):
            delay = _typing_delay(part)
            if index == 0:
                delay = max(0.0, delay - already_spent)
            if delay > 0.05:
                async with client.action(chat_id, "typing"):
                    await asyncio.sleep(delay)
            await _send(chat_id, part)

    def _lock_for(chat_id):
        lock = locks.get(chat_id)
        if lock is None:
            if len(locks) > 2000:
                for key in [k for k, v in locks.items() if not v.locked()]:
                    locks.pop(key, None)
            lock = locks[chat_id] = asyncio.Lock()
        return lock

    def _rate_limited(chat_id) -> bool:
        now = time.monotonic()
        window = hits[chat_id]
        while window and now - window[0] > RATE_WINDOW:
            window.popleft()
        if len(window) >= RATE_LIMIT:
            return True
        window.append(now)
        if len(hits) > 5000:
            for key in [k for k, v in hits.items() if not v]:
                hits.pop(key, None)
        return False

    def _cooldown(kind: str, chat_id, seconds: int) -> bool:
        """True when a notice of this kind was already sent to the chat within ``seconds``."""
        now = time.monotonic()
        key = (kind, chat_id)
        if now - notice_at.get(key, -1e9) < seconds:
            return True
        if len(notice_at) > 5000:
            notice_at.clear()
        notice_at[key] = now
        return False

    async def _notify_admins(text: str, markup=None):
        targets = []
        me_id = ctx.get("me_id")
        if me_id:
            targets.append(me_id)
        try:
            targets.extend(a for a in await asyncio.to_thread(db.list_admins) if a not in targets)
        except Exception:
            logger.warning("userbot: list_admins failed", exc_info=True)
        for target in targets:
            try:
                await bot.send_message(target, _clip(text), reply_markup=markup)
                return True
            except Exception:
                logger.warning("userbot: notify %s failed", target, exc_info=True)
        return False

    async def _handoff(chat_id: int, sender, history, user_text: str, reply_text: str):
        await asyncio.to_thread(
            db.set_userbot_chat_mode, chat_id, "human", sender.first_name or "", sender.username or ""
        )
        await asyncio.to_thread(db.bump_userbot_stat, "handoffs")
        lines = [
            tr("🤝 تحویل چت یوزربات به انسان"),
            f"👤 {html.escape(sender.first_name or '')} (@{html.escape(sender.username or '---')})",
            f"🆔 <code>{sender.id}</code>",
            "",
            tr("دستیار هوشمند در این چت ساکت شد. بعد از پاسخ‌دادن، دکمه‌ی زیر را بزنید تا دوباره خودکار شود."),
            "",
            tr("--- آخرین پیام‌ها ---"),
        ]
        for row in list(history)[-TRANSCRIPT_LINES:]:
            who = tr("👤 مشتری") if row["role"] == "user" else tr("🤖 دستیار")
            lines.append(f"{who}: {html.escape(row['message'])}")
        lines.append(f"{tr('👤 مشتری')}: {html.escape(user_text)}")
        if reply_text:
            lines.append(f"{tr('🤖 دستیار')}: {html.escape(reply_text)}")
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr("▶️ بازگشت به حالت خودکار"), callback_data=f"ubr:{chat_id}")],
            [InlineKeyboardButton(text=tr("💬 باز کردن چت"), url=f"tg://user?id={chat_id}")],
        ])
        await _notify_admins("\n".join(lines), markup)

    async def _send_product_text(chat_id: int, product_id) -> bool:
        """A personal account cannot send inline buttons, so the product card is plain text + deep link."""
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return False
        product = await asyncio.to_thread(db.get_product, product_id)
        if not product or not product["is_active"]:
            return False
        auto = bool(product["is_auto_provision"])
        stock = 0 if auto else await asyncio.to_thread(db.count_available_configs, product_id)
        if not auto and stock <= 0:
            await _send(chat_id, tr("⛔️ موجودی این محصول در حال حاضر تمام شده."))
            return True
        lines = [
            f"📦 {product['name']}",
            f"💰 {tr('قیمت')}: {ul.price_for_users(product, 0):,} {tr('تومان')}",
        ]
        specs = []
        if auto and product["auto_provision_volume_gb"]:
            specs.append(f"📦 {tr('حجم')}: {product['auto_provision_volume_gb']} {tr('گیگ')}")
        if product["duration_days"]:
            specs.append(f"⏳ {tr('مدت')}: {product['duration_days']} {tr('روز')}")
        if specs:
            lines.append(" | ".join(specs))
        if product["description"]:
            lines.append(f"📝 {product['description']}")
        me_bot = await bot.me()
        lines.append("")
        lines.append(f"🛒 {tr('ادامه‌ی خرید در ربات')}:\nhttps://t.me/{me_bot.username}?start=prod_{product_id}")
        await _send(chat_id, "\n".join(lines))
        return True

    async def _media_to_text(msg, kind: str) -> str:
        info = msg.file
        size = getattr(info, "size", 0) or 0
        if kind == "voice":
            if (getattr(info, "duration", 0) or 0) > ai_media.MAX_AUDIO_SECONDS:
                raise ai_media.MediaError("audio_too_long")
            if size > ai_media.MAX_AUDIO_BYTES:
                raise ai_media.MediaError("too_large")
            data = await client.download_media(msg, file=bytes)
            text = await ai_media._gemini_media_text(
                db, data, getattr(info, "mime_type", None) or "audio/ogg", ai_media._AUDIO_PROMPT
            )
            if not text or text.strip() == "[نامفهوم]":
                raise ai_media.MediaError("unintelligible")
            return f"[پیام صوتی - متن خودکار]: {text}"
        if size > ai_media.MAX_IMAGE_BYTES:
            raise ai_media.MediaError("too_large")
        data = await client.download_media(msg, file=bytes)
        desc = await ai_media._image_text(
            db, data, getattr(info, "mime_type", None) or "image/jpeg", ai_media._IMAGE_PROMPT
        )
        if not desc:
            raise ai_media.MediaError("unreadable")
        return f"[تصویر ارسالی کاربر - توضیح خودکار]: {desc}"

    # ------------------------------------------------------------------ answering --------------------
    async def _answer(chat_id: int, entry: dict):
        sender = entry["sender"]
        sender_id = sender.id
        text = _clip("\n".join(entry["parts"]), MAX_INPUT)
        chat = await asyncio.to_thread(db.get_userbot_chat, chat_id)
        if chat is None or chat["mode"] == "human":
            return
        if not flag(db, KEY_ENABLED) or not schedule_allows(db) or paused_by_admin(db, chat_id):
            return

        async with _lock_for(chat_id):
            first = setting(db, KEY_FIRST_MESSAGE)
            if first and not chat["greeted"]:
                await asyncio.to_thread(db.mark_userbot_chat_greeted, chat_id)
                await _send(chat_id, first)
            history = await asyncio.to_thread(db.get_userbot_ai_conversation, chat_id)
            mode = ai_support.BUSINESS_USERBOT if flag(db, KEY_SALES_CARD) else ai_support.BUSINESS_USERBOT_PLAIN
            started = time.monotonic()
            try:
                async with client.action(chat_id, "typing"):
                    result = await ai_support.get_reply(
                        db, sender_id, history, text, business_mode=mode, extra_system=_extra_system(db, sender),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("userbot AI reply failed for user %s", sender_id)
                await asyncio.to_thread(db.bump_userbot_stat, "errors")
                result = {"reply": FALLBACK_REPLY, "escalate": True}
            spent = time.monotonic() - started
            reply = _plain((result.get("reply") or "").strip())

            # The owner may have taken the chat over while the model was thinking: stay silent then.
            latest = await asyncio.to_thread(db.get_userbot_chat, chat_id)
            if latest is None or latest["mode"] == "human" or paused_by_admin(db, chat_id):
                return

            if reply:
                await _send_reply(chat_id, reply, spent)
                await asyncio.to_thread(db.add_userbot_ai_message, chat_id, "user", text)
                await asyncio.to_thread(db.add_userbot_ai_message, chat_id, "model", reply)
                await asyncio.to_thread(db.bump_userbot_chat_ai, chat_id)
                await asyncio.to_thread(db.bump_userbot_stat, "replies")
            if flag(db, KEY_MARK_READ):
                try:
                    own_ack[chat_id] = time.monotonic()
                    await client.send_read_acknowledge(chat_id, entry["msg"])
                except Exception:
                    logger.warning("userbot: read ack failed", exc_info=True)
            if result.get("escalate"):
                await _handoff(chat_id, sender, history, text, reply)
                return
            action = (result.get("ui_action") or {}).get("type")
            if action == "show_product" and flag(db, KEY_SALES_CARD):
                await _send_product_text(chat_id, result["ui_action"].get("product_id"))
            elif action == "deliver_test_config":
                me_bot = await bot.me()
                await _send(
                    chat_id,
                    tr("🧪 برای دریافت کانفیگ تست وارد ربات بشید و دکمه‌ی «کانفیگ تست» را بزنید:")
                    + f"\nhttps://t.me/{me_bot.username}",
                )

    async def _drain(chat_id: int):
        """Waits until the customer stopped typing (debounce), then answers all buffered messages at once."""
        try:
            while True:
                entry = pending.get(chat_id)
                if entry is None:
                    return
                wait = entry["deadline"] - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                    continue
                pending.pop(chat_id, None)
                try:
                    await _answer(chat_id, entry)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("userbot answer failed (chat %s)", chat_id)
                    await asyncio.to_thread(db.bump_userbot_stat, "errors")
                if chat_id not in pending:
                    return
        finally:
            workers.discard(chat_id)

    def _enqueue(chat_id: int, sender, msg, text: str):
        now = time.monotonic()
        delay = max(0, int_setting(db, KEY_DEBOUNCE, 3))
        entry = pending.get(chat_id)
        if entry is None:
            entry = pending[chat_id] = {"parts": [], "first": now, "deadline": now}
        if len(entry["parts"]) < 10:
            entry["parts"].append(text)
        entry["sender"] = sender
        entry["msg"] = msg
        entry["deadline"] = min(now + delay, entry["first"] + MAX_BATCH_WAIT)
        if chat_id not in workers:
            workers.add(chat_id)
            _spawn(_drain(chat_id))

    async def _on_message(event):
        msg = event.message
        chat_id = event.chat_id
        sender_id = event.sender_id
        if not sender_id or sender_id == SERVICE_USER_ID or sender_id == ctx.get("me_id"):
            return
        if _dup((chat_id, msg.id)):
            return
        if not flag(db, KEY_ENABLED):
            return
        if str(db.get_setting(global_switch.SETTING_KEY, "1")).strip() == "0":
            return
        text = (event.raw_text or "").strip()
        kind = _media_kind(msg)
        if not text and kind is None:
            return
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False):
            return
        if flag(db, KEY_SKIP_CONTACTS) and getattr(sender, "contact", False):
            return
        if db.is_admin(sender_id):
            return
        db_user = await asyncio.to_thread(db.get_user, sender_id)
        if db_user and db_user["is_blocked"]:
            return
        if await asyncio.to_thread(db.is_userbot_exception, sender_id):
            return

        chat = await asyncio.to_thread(
            db.touch_userbot_chat, chat_id, sender.first_name or "", sender.username or ""
        )
        if chat["mode"] == "human":
            return
        if not ai_support.is_configured(db) or not schedule_allows(db) or paused_by_admin(db, chat_id):
            return
        if _rate_limited(chat_id):
            return

        if kind in ("voice", "image") and flag(db, KEY_MEDIA_UNDERSTAND):
            try:
                media_text = await _media_to_text(msg, kind)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("userbot: media understanding failed: %s", exc)
                if not _cooldown("media_err", chat_id, 120):
                    await _send(chat_id, ai_media.error_text(exc))
                return
            await asyncio.to_thread(db.bump_userbot_stat, kind)
            text = f"{media_text}\n[متن همراه]: {text}" if text else media_text
        elif kind is not None and not text:
            if flag(db, KEY_MEDIA_ACK) and not _cooldown("media_ack", chat_id, MEDIA_COOLDOWN):
                await _send(chat_id, MEDIA_ACK_TEXT)
            return
        if not text:
            return
        await asyncio.to_thread(db.bump_userbot_stat, "incoming")
        _enqueue(chat_id, sender, msg, text)

    async def _owner_command(event, text: str):
        """`.ai off` / `.ai on` typed by the owner inside a customer chat. The command message is deleted."""
        chat_id = event.chat_id
        if chat_id == ctx.get("me_id"):
            return
        turn_on = text == ".ai on"
        try:
            chat = await event.get_chat()
        except Exception:
            chat = None
        first_name = (getattr(chat, "first_name", "") or "") if chat else ""
        username = (getattr(chat, "username", "") or "") if chat else ""
        pending.pop(chat_id, None)
        if turn_on:
            STATE["chat_active"].pop(chat_id, None)
            await asyncio.to_thread(db.set_userbot_chat_mode, chat_id, "auto", first_name, username)
            await asyncio.to_thread(db.clear_userbot_ai_conversation, chat_id)
        else:
            await asyncio.to_thread(db.set_userbot_chat_mode, chat_id, "human", first_name, username)
        try:
            await event.delete()
        except Exception:
            logger.warning("userbot: could not delete the command message", exc_info=True)
        label = f"{first_name} (@{username})" if username else (first_name or str(chat_id))
        await _notify_admins(
            (tr("✅ هوش مصنوعی در این چت روشن شد") if turn_on else tr("🔇 هوش مصنوعی در این چت خاموش شد"))
            + f": {html.escape(label)}"
        )

    async def _on_outgoing(event):
        if not event.is_private:
            return
        if event.message.id in own_ids:
            return
        text = (event.raw_text or "").strip().lower()
        if text in (".ai on", ".ai off"):
            await _owner_command(event, text)
            return
        last = own_send.get(event.chat_id)
        if last is None or time.monotonic() - last >= SELF_ECHO_WINDOW:
            mark_admin_active(event.chat_id)

    async def _on_read(event):
        chat_id = getattr(event, "chat_id", None)
        last = own_ack.get(chat_id)
        if last is None or time.monotonic() - last >= SELF_ECHO_WINDOW:
            mark_admin_active(chat_id)

    def _safe(fn):
        async def wrapper(event):
            try:
                await fn(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                STATE["last_error"] = f"{fn.__name__} failed"
                logger.exception("userbot handler %s failed (chat %s)", fn.__name__, getattr(event, "chat_id", None))
        return wrapper

    async def _maintenance():
        while True:
            await asyncio.sleep(MAINTENANCE_INTERVAL)
            try:
                hours = int_setting(db, KEY_HUMAN_TTL, 0)
                if hours > 0:
                    await asyncio.to_thread(db.expire_userbot_human_chats, hours)
            except Exception:
                logger.warning("userbot: maintenance failed", exc_info=True)

    client.add_event_handler(_safe(_on_message), events.NewMessage(incoming=True, func=lambda e: e.is_private))
    client.add_event_handler(_safe(_on_outgoing), events.NewMessage(outgoing=True))
    client.add_event_handler(_safe(_on_read), events.MessageRead(inbox=True))
    maintenance_task = asyncio.create_task(_maintenance())

    try:
        while True:
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise RuntimeError("AuthKeyUnregisteredError")
                me = await client.get_me()
                ctx["me_id"] = me.id
                STATE["me"] = {"id": me.id, "first_name": me.first_name or "", "username": me.username or ""}
                STATE["connected"] = True
                STATE["connected_at"] = time.time()
                STATE["last_error"] = ""
                logger.info("userbot connected as %s (@%s)", me.id, me.username)
                await client.run_until_disconnected()
                STATE["connected"] = False
                logger.warning("userbot disconnected; reconnecting in %ss", RETRY_DELAY)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                STATE["connected"] = False
                STATE["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
                if type(exc).__name__ in AUTH_LOST_ERRORS or "AuthKeyUnregisteredError" in str(exc):
                    logger.error("userbot session is no longer valid: %s", exc)
                    await _notify_admins(
                        "⚠️ Telegram userbot session is no longer valid. "
                        "Log in again from the server menu (Telegram userbot login)."
                    )
                    return
                logger.warning("userbot error: %s; retrying in %ss", exc, RETRY_DELAY, exc_info=True)
            await asyncio.sleep(RETRY_DELAY)
    finally:
        STATE["connected"] = False
        maintenance_task.cancel()
        for task in list(tasks):
            task.cancel()
        try:
            await client.disconnect()
        except Exception:
            pass
        try:
            await bot.session.close()
        except Exception:
            pass


def _cli(argv) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "login":
        return 0 if asyncio.run(interactive_login()) else 1
    if cmd == "logout":
        asyncio.run(logout())
        print("Userbot session removed.")
        return 0
    if cmd == "status":
        creds = load_session()
        if creds is None:
            print("not logged in")
            return 1
        user = creds["user"]
        print(f"logged in: {user.get('first_name', '')} (@{user.get('username') or '-'}) id={user.get('id')}")
        return 0
    print("usage: userbot.py login|logout|status")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
