# -*- coding: utf-8 -*-
"""Telegram user-account login (MTProto) and AI support auto-reply in the owner's private chats."""

import asyncio
import getpass
import html
import json
import logging
import os
import random
import sys
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

SESSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "userbot_session.json")
CONN_PREFIX = "userbot:"
SERVICE_USER_ID = 777000
FALLBACK_REPLY = "یه مشکلی پیش اومد؛ پیامت رو برای پشتیبانی انسانی می‌فرستم."
KEY_MARK_READ = "business_mark_read"
KEY_ENABLED = "userbot_enabled"
KEY_PAUSE_WHEN_ACTIVE = "userbot_pause_when_active"
KEY_AWAY_MINUTES = "userbot_away_minutes"
AWAY_CHOICES = (2, 5, 10, 30, 60)
SELF_ECHO_WINDOW = 3
STATE = {"last_activity": None, "connected": False, "db_path": None}
MAX_TEXT = 4096
TRANSCRIPT_LINES = 10
RATE_WINDOW = 60
RATE_LIMIT = 10
RETRY_DELAY = 30
AUTH_LOST_ERRORS = {
    "AuthKeyUnregisteredError", "AuthKeyDuplicatedError", "SessionRevokedError",
    "SessionExpiredError", "UserDeactivatedError", "UserDeactivatedBanError",
}


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


def get_away_minutes(db) -> int:
    try:
        value = int(str(db.get_setting(KEY_AWAY_MINUTES, "5")).strip())
    except ValueError:
        return 5
    return value if value > 0 else 5


def mark_admin_active():
    STATE["last_activity"] = time.monotonic()


def admin_active(db) -> bool:
    last = STATE["last_activity"]
    return last is not None and time.monotonic() - last < get_away_minutes(db) * 60


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


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def run(db, bot_token: str):
    """Run the userbot until cancelled; no-op when no session is stored or telethon is missing."""
    STATE["db_path"] = db.db_path
    creds = load_session()
    if creds is None:
        return
    try:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
    except ImportError:
        logger.warning("userbot session found but telethon is not installed; run: pip install telethon")
        return

    import ai_support
    import global_switch
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

    async def _send(chat_id, text: str):
        if len(own_send) > 5000:
            own_send.clear()
        own_send[chat_id] = time.monotonic()
        msg = await client.send_message(chat_id, text, parse_mode=None)
        own_send[chat_id] = time.monotonic()
        return msg

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

    async def _handoff(conn_row: int, chat_id: int, sender, history, user_text: str, reply_text: str):
        await asyncio.to_thread(db.set_business_chat_mode, conn_row, chat_id, "human")
        lines = [
            tr("🤝 تحویل چت بیزنس به انسان"),
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
            [InlineKeyboardButton(text=tr("▶️ بازگشت به حالت خودکار"), callback_data=f"bizr:{conn_row}:{chat_id}")],
            [InlineKeyboardButton(text=tr("💬 باز کردن چت"), url=f"tg://user?id={chat_id}")],
        ])
        await _notify_admins("\n".join(lines), markup)
        await asyncio.to_thread(db.clear_business_ai_conversation, conn_row, chat_id)

    async def _on_message(event):
        text = (event.raw_text or "").strip()
        chat_id = event.chat_id
        sender_id = event.sender_id
        if not text or not sender_id or sender_id == SERVICE_USER_ID:
            return
        if str(db.get_setting(KEY_ENABLED, "1")).strip() != "1":
            return
        if str(db.get_setting(global_switch.SETTING_KEY, "1")).strip() == "0":
            return
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False):
            return
        conn = await asyncio.to_thread(db.get_business_connection, ctx["connection_id"])
        if conn is None or not conn["is_enabled"] or not conn["auto_reply"]:
            return
        conn_row = conn["id"]
        if db.is_admin(sender_id):
            return
        db_user = await asyncio.to_thread(db.get_user, sender_id)
        if db_user and db_user["is_blocked"]:
            return
        if await asyncio.to_thread(db.is_business_exception, conn_row, sender_id):
            return
        if str(db.get_setting(KEY_PAUSE_WHEN_ACTIVE, "1")).strip() == "1" and admin_active(db):
            return

        chat = await asyncio.to_thread(
            db.touch_business_chat, conn_row, chat_id, sender.first_name or "", sender.username or ""
        )
        await asyncio.to_thread(db.log_business_message, conn_row, chat_id, event.message.id, sender_id, text)
        if chat["mode"] == "human" or not ai_support.is_configured(db) or _rate_limited(chat_id):
            return

        async with _lock_for(chat_id):
            chat = await asyncio.to_thread(db.get_business_chat, conn_row, chat_id)
            if chat is None or chat["mode"] == "human":
                return
            if conn["first_message"] and not chat["greeted"]:
                await asyncio.to_thread(db.mark_business_chat_greeted, conn_row, chat_id)
                await _send(chat_id, _clip(conn["first_message"]))
            history = await asyncio.to_thread(db.get_business_ai_conversation, conn_row, chat_id)
            try:
                async with client.action(chat_id, "typing"):
                    result = await ai_support.get_reply(db, sender_id, history, text, business_mode=True)
                    await asyncio.sleep(random.uniform(0.4, 1.2))
            except Exception:
                logger.exception("userbot AI reply failed for user %s", sender_id)
                result = {"reply": FALLBACK_REPLY, "escalate": True}
            reply = (result.get("reply") or "").strip()
            if reply:
                await _send(chat_id, _clip(reply))
                await asyncio.to_thread(db.add_business_ai_message, conn_row, chat_id, "user", text)
                await asyncio.to_thread(db.add_business_ai_message, conn_row, chat_id, "model", reply)
            if str(db.get_setting(KEY_MARK_READ, "0")).strip() == "1":
                try:
                    own_ack[chat_id] = time.monotonic()
                    await client.send_read_acknowledge(chat_id, event.message)
                except Exception:
                    logger.warning("userbot: read ack failed", exc_info=True)
            if result.get("escalate"):
                await _handoff(conn_row, chat_id, sender, history, text, reply)
                return
            if (result.get("ui_action") or {}).get("type") == "deliver_test_config":
                me_bot = await bot.me()
                await _send(
                    chat_id,
                    tr("🧪 برای دریافت کانفیگ تست وارد ربات بشید و دکمه‌ی «کانفیگ تست» را بزنید:")
                    + f"\nhttps://t.me/{me_bot.username}",
                )

    async def _on_outgoing(event):
        last = own_send.get(event.chat_id)
        if last is None or time.monotonic() - last >= SELF_ECHO_WINDOW:
            mark_admin_active()

    async def _on_read(event):
        last = own_ack.get(getattr(event, "chat_id", None))
        if last is None or time.monotonic() - last >= SELF_ECHO_WINDOW:
            mark_admin_active()

    def _safe(fn):
        async def wrapper(event):
            try:
                await fn(event)
            except Exception:
                logger.exception("userbot handler %s failed (chat %s)", fn.__name__, getattr(event, "chat_id", None))
        return wrapper

    client.add_event_handler(_safe(_on_message), events.NewMessage(incoming=True, func=lambda e: e.is_private))
    client.add_event_handler(_safe(_on_outgoing), events.NewMessage(outgoing=True))
    client.add_event_handler(_safe(_on_read), events.MessageRead(inbox=True))

    try:
        while True:
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise RuntimeError("AuthKeyUnregisteredError")
                me = await client.get_me()
                ctx["me_id"] = me.id
                ctx["connection_id"] = f"{CONN_PREFIX}{me.id}"
                await asyncio.to_thread(
                    db.upsert_business_connection, ctx["connection_id"], me.id, me.id,
                    True, True, True, me.first_name or "", me.username or "",
                )
                logger.info("userbot connected as %s (@%s)", me.id, me.username)
                STATE["connected"] = True
                await client.run_until_disconnected()
                STATE["connected"] = False
                logger.warning("userbot disconnected; reconnecting in %ss", RETRY_DELAY)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if type(exc).__name__ in AUTH_LOST_ERRORS or "AuthKeyUnregisteredError" in str(exc):
                    logger.error("userbot session is no longer valid: %s", exc)
                    if ctx.get("connection_id"):
                        await asyncio.to_thread(
                            db.upsert_business_connection, ctx["connection_id"], ctx["me_id"], ctx["me_id"],
                            False, False, False, "", "",
                        )
                    await _notify_admins(
                        "⚠️ Telegram userbot session is no longer valid. "
                        "Log in again from the server menu (Telegram userbot login)."
                    )
                    return
                logger.warning("userbot error: %s; retrying in %ss", exc, RETRY_DELAY, exc_info=True)
            await asyncio.sleep(RETRY_DELAY)
    finally:
        STATE["connected"] = False
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
