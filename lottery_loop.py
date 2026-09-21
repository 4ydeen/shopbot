# -*- coding: utf-8 -*-
"""حلقه امتیاز و قرعه‌کشی شبانه F18."""
import asyncio
import html
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _seconds_to_next_midnight():
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=3, microsecond=0)
    return max(1, (tomorrow - now).total_seconds())


async def _report_result(bot, db, result):
    if result.get("status") != "completed":
        return
    winners = result.get("winners", [])
    lines = ["🎉 قرعه‌کشی شبانه انجام شد!", "", "🏆 برندگان:"]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for w in winners:
        who = html.escape(f"@{w['username']}" if w.get("username") else (w.get("first_name") or str(w["user_id"])))
        if result.get("prize_type") == "discount":
            prize = f"کد تخفیف {w['prize']}٪" + (f" — <code>{w['code']}</code>" if w.get("code") else "")
        else:
            prize = f"{w['prize']:,} تومان شارژ کیف پول"
        lines.append(f"{medals.get(w['rank'], '🏅')} نفر {w['rank']}: {who} — {w['score']} امتیاز — {prize}")
    text = "\n".join(lines)
    chat_id = db.get_setting("lottery_report_chat_id", "") or ""
    targets = []
    if chat_id.strip():
        try:
            targets = [int(chat_id.strip())]
        except ValueError:
            targets = []
    if not targets:
        try:
            targets = await asyncio.to_thread(db.list_admins)
        except Exception:
            targets = []
    for target in targets:
        try:
            await bot.send_message(target, text, parse_mode="HTML")
        except Exception as exc:
            logger.info("F18: ارسال گزارش قرعه‌کشی به %s ناموفق بود: %s", target, exc)
    for w in winners:
        try:
            if result.get("prize_type") == "discount" and w.get("code"):
                msg = f"🎉 تبریک! شما نفر {w['rank']} قرعه‌کشی شبانه شدید.\n🎟 کد تخفیف: <code>{w['code']}</code>\n⏳ اعتبار: {w.get('expires_at', '')}"
            elif result.get("prize_type") == "wallet":
                msg = f"🎉 تبریک! شما نفر {w['rank']} قرعه‌کشی شبانه شدید و {w['prize']:,} تومان به کیف پولتان اضافه شد."
            else:
                continue
            await bot.send_message(w["user_id"], msg, parse_mode="HTML")
        except Exception:
            pass


async def lottery_once(bot, db, lottery_date=None):
    result = await asyncio.to_thread(db.run_lottery_once, lottery_date)
    await _report_result(bot, db, result)
    return result


async def lottery_loop(bot, db):
    """هر شب پس از نیمه‌شب یک بار قرعه‌کشی را اجرا می‌کند."""
    while True:
        try:
            await asyncio.sleep(_seconds_to_next_midnight())
            await lottery_once(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("خطا در حلقه F18 lottery")
            await asyncio.sleep(60)
