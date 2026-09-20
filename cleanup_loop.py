# -*- coding: utf-8 -*-
"""پاکسازی دوره‌ای سرویس‌های منقضی (F14).

طراحی عمدی:
- expired_delete_days و test_delete_days با مقدار ۰ خاموش هستند.
- قبل از حذف، سرویس روی پنل soft-disable می‌شود و رکورد DB باقی می‌ماند.
- On-hold، نامحدود و auto-renew هرگز وارد حذف نمی‌شوند.
- dry-run به‌صورت پیش‌فرض روشن است تا اولین انتشار فقط نامزدهای حذف را به ادمین نشان دهد.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import report_router
from panel_providers import get_provider

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.utcnow()


def _parse_iso(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _safe_int(db, key, default=0):
    try:
        return max(0, int(db.get_setting(key, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _safe_bool(db, key, default=True):
    raw = str(db.get_setting(key, "1" if default else "0") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def _notify_user(bot: Bot, user_id: int, text: str, product_id=None):
    markup = None
    if product_id:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data=f"prod:{int(product_id)}")
        ]])
    try:
        await bot.send_message(user_id, text, reply_markup=markup)
    except Exception as exc:
        logger.info("ارسال پیام پاکسازی به کاربر %s ناموفق بود: %s", user_id, exc)


async def _notify_admins(bot: Bot, db, text: str):
    try:
        admin_ids = await asyncio.to_thread(db.list_admins)
    except Exception:
        admin_ids = []
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass


async def _provider_action(db, row, action):
    """action = 'disable' | 'delete'. نتیجه False یعنی عملیات روی پنل قطعی نشده."""
    server = await asyncio.to_thread(db.get_panel_server, row["panel_server_id"])
    if not server or not server["is_active"]:
        return False, "پنل پیدا نشد یا غیرفعال است"
    try:
        provider = get_provider(server)
        if action == "disable":
            result = await provider.set_enabled(row["username"], False)
        else:
            result = await provider.delete_user(row["username"])
        # برخی providerها None برمی‌گردانند ولی بدون exception موفق‌اند.
        return (result is not False), "ok"
    except Exception as exc:
        return False, str(exc)


async def cleanup_once(bot: Bot, db):
    """یک دور پاکسازی را اجرا می‌کند. برای تست واحد نیز قابل فراخوانی است."""
    now = _utcnow()
    now_iso = now.isoformat()
    expired_days = _safe_int(db, "expired_delete_days", 0)
    test_days = _safe_int(db, "test_delete_days", 0)
    warning_days = _safe_int(db, "expired_cleanup_warning_days", 3)
    dry_run = _safe_bool(db, "expired_cleanup_dry_run", True)

    if expired_days == 0 and test_days == 0:
        return {"soft": 0, "deleted": 0, "warned": 0, "dry_run": dry_run, "candidates": []}

    # dry-run: هیچ تغییر روی پنل/DB انجام نمی‌دهیم و فقط فهرست نامزدها را به ادمین می‌دهیم.
    rows = await asyncio.to_thread(db.get_cleanup_candidates, now_iso)
    candidates = []
    for row in rows:
        is_test = (row["source"] or "") == "test"
        grace_days = test_days if is_test else expired_days
        if grace_days <= 0:
            continue
        exp = _parse_iso(row["expires_at"])
        if not exp:
            continue
        candidates.append((row, is_test, grace_days, exp))

    if dry_run:
        if candidates:
            lines = ["🧪 F14 — dry-run پاکسازی سرویس‌های منقضی", ""]
            for row, is_test, grace, exp in candidates[:30]:
                lines.append(
                    f"{'🧪 تست' if is_test else '📦 سرویس'} #{row['id']} | "
                    f"کاربر {row['user_id']} | انقضا {exp.strftime('%Y-%m-%d %H:%M')} | مهلت حذف {grace} روز"
                )
            if len(candidates) > 30:
                lines.append(f"… و {len(candidates) - 30} مورد دیگر")
            await _notify_admins(bot, db, "\n".join(lines))
        return {"soft": 0, "deleted": 0, "warned": 0, "dry_run": True, "candidates": [r[0]["id"] for r in candidates]}

    soft_count = deleted_count = warned_count = 0

    # هشدار قبل از انقضا؛ هشدار صرفاً وقتی سرویس هنوز active است ارسال می‌شود.
    warning_to = (now + timedelta(days=warning_days)).isoformat()
    warning_rows = await asyncio.to_thread(db.get_cleanup_warning_candidates, now_iso, warning_to)
    for row in warning_rows:
        is_test = (row["source"] or "") == "test"
        grace_days = test_days if is_test else expired_days
        if grace_days <= 0:
            continue
        if await asyncio.to_thread(db.mark_cleanup_warning_sent, row["id"], now_iso):
            warned_count += 1
            await _notify_user(
                bot,
                row["user_id"],
                "⚠️ سرویس شما به‌زودی منقضی می‌شود. لطفاً در صورت نیاز، قبل از پایان مهلت آن را تمدید یا سرویس جدید تهیه کنید.",
                row["product_id"] if "product_id" in row.keys() else None,
            )

    for row, is_test, grace_days, exp in candidates:
        # soft-disable در همان لحظه‌ی انقضا.
        if not row["cleanup_soft_disabled_at"]:
            ok, reason = await _provider_action(db, row, "disable")
            if not ok:
                logger.warning("F14: soft-disable سرویس #%s ناموفق: %s", row["id"], reason)
                continue
            if await asyncio.to_thread(db.mark_cleanup_soft_disabled, row["id"], now_iso):
                soft_count += 1
                await asyncio.to_thread(
                    db.add_custom_config_history,
                    row["id"], "cleanup_soft_disable",
                    f"F14: انقضا؛ مهلت حذف {grace_days} روز",
                )
            continue

        # حذف نهایی فقط پس از گذشت مهلت از زمان انقضا.
        delete_at = exp + timedelta(days=grace_days)
        if now < delete_at:
            continue
        ok, reason = await _provider_action(db, row, "delete")
        if not ok:
            logger.warning("F14: حذف سرویس #%s ناموفق: %s", row["id"], reason)
            continue
        if await asyncio.to_thread(db.mark_cleanup_deleted, row["id"], now_iso):
            deleted_count += 1
            await asyncio.to_thread(
                db.add_custom_config_history,
                row["id"], "cleanup_delete",
                f"F14: حذف قطعی پس از {grace_days} روز مهلت",
            )
            if is_test:
                await _notify_user(
                    bot,
                    row["user_id"],
                    "🧪 تست شما تمام شد و از پنل حذف شد. برای ادامه، می‌توانید یک سرویس خریداری کنید.",
                    row["product_id"] if "product_id" in row.keys() else None,
                )
            else:
                await _notify_user(
                    bot,
                    row["user_id"],
                    "⛔ سرویس منقضی شما پس از پایان مهلت نگهداری از پنل حذف شد.",
                    row["product_id"] if "product_id" in row.keys() else None,
                )

    if soft_count or deleted_count:
        lines = ["📋 F14 — گزارش پاکسازی سرویس‌های منقضی", ""]
        if soft_count:
            lines.append(f"🔕 غیرفعال‌شده (soft-disable): {soft_count} سرویس")
        if deleted_count:
            lines.append(f"🗑 حذف‌شده از پنل: {deleted_count} سرویس")
        if warned_count:
            lines.append(f"⚠️ هشدار پیش از انقضا برای: {warned_count} سرویس")
        try:
            await report_router.report(bot, db, "service", "\n".join(lines))
        except Exception:
            logger.warning("ارسال گزارش پاکسازی F14 ناموفق بود.", exc_info=True)

    return {
        "soft": soft_count,
        "deleted": deleted_count,
        "warned": warned_count,
        "dry_run": False,
        "candidates": [r["id"] for r, *_ in candidates],
    }


async def cleanup_loop(bot: Bot, db, interval: int = 3600):
    """حلقه‌ی ساعتی پاکسازی؛ تنظیمات هر دور دوباره خوانده می‌شوند."""
    while True:
        try:
            await cleanup_once(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("خطا در حلقه F14 cleanup")
        await asyncio.sleep(max(300, int(interval)))
