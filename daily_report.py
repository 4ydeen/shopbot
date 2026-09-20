# -*- coding: utf-8 -*-
"""گزارش روزانه‌ی فروش برای مدیران، در ساعت تنظیم‌شده به وقت تهران (پیش‌فرض ۲۳:۴۵)."""

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone

import report_router
from jalali import to_jalali_str

try:
    from zoneinfo import ZoneInfo
    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:
    TEHRAN = timezone(timedelta(hours=3, minutes=30))

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60
DEFAULT_TIME = (23, 45)
STATUS_KEY_LAST_DATE = "_job_daily_report_last_date"
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


async def _db(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def parse_report_time(value: str) -> tuple:
    try:
        hour, minute = (int(part) for part in str(value).strip().split(":"))
    except ValueError:
        return DEFAULT_TIME
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return DEFAULT_TIME


def build_report_text(db, now_tehran: datetime) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats = db.get_sales_stats(day, day)
    extras = db.get_daily_report_extras(day)
    store = html.escape(db.get_setting("store_name", "") or "")
    lines = [
        f"📊 گزارش روزانه‌ی فروش{' - ' + store if store else ''}",
        f"📅 {WEEKDAYS_FA[now_tehran.weekday()]} {to_jalali_str(now_tehran)}",
        "",
        f"🛒 سفارش تاییدشده: {stats['approved']:,}",
        f"💰 درآمد: {stats['revenue']:,} تومان",
        f"🧾 میانگین سبد خرید: {stats['aov']:,} تومان",
        f"⏳ در انتظار: {stats['pending']:,} | ❌ ردشده: {stats['rejected']:,}",
        f"💳 شارژ کیف پول: {extras['topup_count']:,} مورد، {extras['topup_amount']:,} تومان",
        f"🧪 کانفیگ تست: {extras['test_count']:,}",
        f"👥 کاربر جدید: {stats['new_users']:,}",
    ]
    top = stats.get("top_products") or []
    if top:
        lines += ["", "🏆 پرفروش‌ترین‌ها:"]
        lines += [f"{i}. {html.escape(p['name'])}: {p['orders']:,} عدد" for i, p in enumerate(top[:3], 1)]
    return "\n".join(lines)


async def check_and_send_daily_report(bot, db) -> bool:
    if db.get_setting("daily_report_enabled", "1") != "1":
        return False
    now = datetime.now(TEHRAN)
    today = now.strftime("%Y-%m-%d")
    hour, minute = parse_report_time(db.get_setting("daily_report_time", "23:45"))
    if (now.hour, now.minute) < (hour, minute):
        return False
    if db.get_setting(STATUS_KEY_LAST_DATE, "") == today:
        return False

    text = await _db(build_report_text, db, now)
    await report_router.report(bot, db, "nightly", text, senior_only=True)
    await _db(db.set_setting, STATUS_KEY_LAST_DATE, today)
    return True


async def daily_report_loop(bot, db, interval_seconds: int = CHECK_INTERVAL_SECONDS) -> None:
    while True:
        try:
            await check_and_send_daily_report(bot, db)
        except Exception:
            logger.exception("خطا در چرخه‌ی گزارش روزانه‌ی فروش")
        await asyncio.sleep(interval_seconds)
