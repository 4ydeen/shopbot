# -*- coding: utf-8 -*-
"""
دستیار پشتیبانی هوش مصنوعی (Google Gemini)

هدف: قبل از رسیدن پیام کاربر به ادمین انسانی، یک لایه‌ی هوشمند سوال‌های
تکراری/قابل‌پاسخ‌گویی خودکار را جواب بدهد:
  - سوالات متداول (نحوه‌ی اتصال، تفاوت پلن‌ها، سیاست بازگشت وجه و ...) که
    متنش را خودِ ادمین در تنظیمات ("ai_support_faq") می‌نویسد.
  - سوالات مربوط به وضعیت واقعیِ خودِ کاربر (سرویس، انقضا، کیف پول، سفارش‌ها)
    که با function calling مستقیماً از دیتابیس خوانده می‌شود - نه حدس زدن.

قوانین سخت‌گیرانه (در system prompt هم تکرار شده‌اند):
  - این ماژول هیچ عملیات نوشتنی (رفاند، تمدید، تغییر دیتابیس، تخفیف) انجام
    نمی‌دهد؛ همه‌ی ابزارها فقط خواندنی هستند.
  - هر وقت موضوع مالی/شکایت/رفاند بود یا کاربر صراحتاً خواست، مکالمه با ابزار
    escalate_to_human به پشتیبانی انسانی ارجاع داده می‌شود.

اگر هیچ کلید API (نه از پنل بات، نه از .env) تنظیم نشده باشد، get_reply()
بدون تلاش برای اتصال به API بلافاصله escalate=True برمی‌گرداند تا کاربر
معطل نماند. کلید API از داخل پنل ادمین بات (دستیار هوشمند → تنظیم کلید API)
هم قابل تنظیم است - در آن صورت نیازی به .env یا ری‌استارت سرور نیست.
"""

import asyncio
import logging
from datetime import datetime, timezone

import config
from sub_info import fetch_sub_info
from jalali import to_jalali_str
from panel_providers import get_provider, PanelError

_log = logging.getLogger("ai_support")

# حداکثر تعداد دوری که مدل مجاز است پشت‌سرهم ابزار صدا بزند، قبل از این‌که
# مجبورش کنیم یک جواب متنی نهایی بدهد (جلوگیری از حلقه‌ی بی‌نهایت تابع‌زنی).
_MAX_TOOL_ROUNDS = 4

_SYSTEM_PROMPT_TEMPLATE = """تو دستیار پشتیبانی فارسی‌زبان یک فروشگاه فروش اشتراک VPN (V2Ray/کانفیگ) هستی.

قوانین اجباری:
۱. فقط بر اساس اطلاعات واقعی که از ابزارها (tools) می‌گیری یا در «دانش پایه» زیر آمده جواب بده. هرگز چیزی را حدس نزن یا وعده‌ی چیزی که مطمئن نیستی نده.
۲. تو هیچ اختیار مالی/اجرایی نداری: نمی‌توانی رفاند بدهی، سرویس را تمدید کنی، تخفیف بدهی یا کانفیگ بسازی. اگر کاربر همچین چیزی خواست، مودبانه توضیح بده که این کار را باید پشتیبانی انسانی انجام بدهد و ابزار escalate_to_human را صدا بزن.
۳. اگر کاربر صراحتاً خواست با انسان صحبت کند، ناراحت/عصبانی بود، یا موضوع شکایت/اختلاف مالی بود، بلافاصله (بدون معطلی و بدون اصرار برای ادامه‌ی گفتگو با تو) escalate_to_human را صدا بزن.
۴. اگر سوال درباره‌ی وضعیت شخصیِ خودِ کاربر است (سرویسش، حجم باقی‌مانده، انقضا، موجودی کیف پول، سفارش‌ها)، همیشه اول ابزار مربوطه را صدا بزن؛ از حافظه یا حدس جواب نده.
۴-۱. برای اینکه سرویس «فعال» یا «غیرفعال» است، فقط و فقط به فیلد panel_status نگاه کن (اگر موجود بود)؛ داشتنِ حجم باقی‌مانده یا نرسیدن تاریخ انقضا به این معنی نیست که سرویس روشن است - ممکن است دستی یا به هر دلیلی روی پنل خاموش شده باشد.
۵. کوتاه، دوستانه و محاوره‌ای فارسی بنویس؛ از ایموجی مناسب (نه زیاد) استفاده کن. از پاراگراف‌های طولانی خودداری کن.
۶. اگر بعد از تلاش نتوانستی مشکل را حل کنی، صادقانه بگو و escalate_to_human را صدا بزن؛ کاربر را سردرگم نگه نداری.

دانش پایه (تنظیم‌شده توسط ادمین فروشگاه):
{faq}
"""

_TOOLS = [
    {
        "name": "check_account_status",
        "description": (
            "وضعیت واقعی حساب کاربر را برمی‌گرداند: موجودی کیف پول، لیست "
            "سرویس‌های فعال با حجم/انقضای زنده، و سفارش‌های در انتظار بررسی. "
            "برای هر سوالی درباره‌ی «چرا وصل نمیشم»، «حجمم چقدر مونده»، "
            "«کی تموم میشه»، «موجودی کیف پولم چقدره» این ابزار را صدا بزن."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "escalate_to_human",
        "description": (
            "مکالمه را به پشتیبانی انسانی (تیکت) ارجاع می‌دهد. برای درخواست "
            "صریح صحبت با انسان، موضوعات مالی/رفاند/شکایت، یا وقتی خودت "
            "نمی‌توانی مشکل را حل کنی صدا بزن."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "خلاصه‌ی یک‌خطی از موضوع، برای نمایش به ادمین.",
                }
            },
            "required": ["reason"],
        },
    },
]


def resolve_gemini_key(db) -> str:
    """کلید API Gemini را برمی‌گرداند: اولویت با کلیدی است که ادمین از داخل
    پنل بات تنظیم کرده؛ در غیر این صورت کلید سراسری .env (اگر باشد)."""
    return db.get_setting("gemini_api_key", "") or config.GEMINI_API_KEY


def resolve_gemini_key_source(db) -> str:
    """برای نمایش در پنل ادمین: کلید از کجا آمده؟ 'db' یعنی از داخل بات
    تنظیم شده (فوری، بدون نیاز به ری‌استارت سرور). 'env' یعنی فقط از .env
    این پروسه خوانده شده. 'none' یعنی هیچ‌کدام تنظیم نشده."""
    if db.get_setting("gemini_api_key", ""):
        return "db"
    if config.GEMINI_API_KEY:
        return "env"
    return "none"


def is_configured(db) -> bool:
    return bool(resolve_gemini_key(db))


def _gb(n: int) -> float:
    return round(n / (1024 ** 3), 2)


def _summarize_sub_info(info: dict) -> dict:
    """خروجی خام fetch_sub_info را به فیلدهای ساده و خوانا برای مدل تبدیل
    می‌کند (به‌جای بایت خام و timestamp، گیگابایت و تاریخ شمسی)."""
    if not info or not info.get("ok"):
        return {"data_available": False}
    used = info.get("upload", 0) + info.get("download", 0)
    total = info.get("total", 0)
    out = {
        "data_available": True,
        "used_gb": _gb(used),
        "total_gb": _gb(total) if total else "نامحدود",
    }
    if total:
        out["remaining_gb"] = _gb(max(0, total - used))
    expire = info.get("expire")
    if expire:
        exp_dt = datetime.fromtimestamp(expire, tz=timezone.utc)
        out["expires_at_jalali"] = to_jalali_str(exp_dt)
        out["days_left"] = max(0, (exp_dt - datetime.now(timezone.utc)).days)
        out["is_expired"] = exp_dt < datetime.now(timezone.utc)
    else:
        out["expires_at_jalali"] = "نامحدود"
    return out


async def _tool_check_account_status(db, user_tg_id: int) -> dict:
    def _read():
        wallet = db.get_wallet_credit(user_tg_id)
        orders = db.get_user_orders(user_tg_id)
        custom_configs = db.get_custom_configs_for_user(user_tg_id)
        return wallet, orders, custom_configs

    wallet, orders, custom_configs = await asyncio.to_thread(_read)

    pending = [
        {"order_id": o["id"], "status": o["status"]}
        for o in orders
        if o["status"] not in ("approved", "rejected")
    ]

    services = []
    approved_with_config = [o for o in orders if o["status"] == "approved" and o["config_id"]]
    for o in approved_with_config:
        cfg = await asyncio.to_thread(db.get_config_by_id, o["config_id"])
        if not cfg or not cfg["link"]:
            continue
        try:
            info = await fetch_sub_info(cfg["link"])
        except Exception:
            _log.exception("خطا هنگام خواندن sub_info برای کاربر %s در ابزار AI.", user_tg_id)
            info = {}
        entry = {"order_id": o["id"]}
        entry.update(_summarize_sub_info(info))
        services.append(entry)

    for cc in custom_configs:
        sub_url = cc["subscription_url"]
        entry = {
            "name": cc["display_name"] or cc["username"],
            "enabled": bool(cc["enabled"]) if "enabled" in cc.keys() else True,
        }
        if sub_url:
            try:
                info = await fetch_sub_info(sub_url)
                entry.update(_summarize_sub_info(info))
            except Exception:
                _log.exception("خطا هنگام خواندن sub_info برای کانفیگ شخصی کاربر %s.", user_tg_id)
                entry["data_available"] = False
        else:
            entry["data_available"] = False

        # توجه: هدر subscription-userinfo (بالا) فقط حجم/انقضا را می‌دهد و در
        # خیلی از پنل‌ها (از جمله 3x-ui) حتی برای کاربر غیرفعال‌شده هم برمی‌گردد؛
        # پس برای وضعیت واقعیِ روشن/خاموش بودن باید مستقیماً از خودِ پنل (همان
        # API ادمین که ساخت/تمدید کانفیگ هم با آن انجام می‌شود) بپرسیم.
        try:
            server = await asyncio.to_thread(db.get_panel_server, cc["panel_server_id"])
            if server:
                provider = get_provider(server)
                usage = await provider.get_user_usage(cc["username"])
                entry["panel_status"] = (
                    "فعال" if usage.get("status") == "active" else "غیرفعال"
                )
        except PanelError:
            _log.exception("خطا هنگام خواندن وضعیت واقعی از پنل برای کانفیگ شخصی کاربر %s.", user_tg_id)
        except Exception:
            _log.exception("خطای غیرمنتظره هنگام خواندن وضعیت پنل برای کاربر %s.", user_tg_id)

        services.append(entry)

    return {
        "wallet_balance_toman": wallet,
        "active_services": services,
        "pending_orders": pending,
    }


async def _run_tool(db, user_tg_id: int, name: str, args: dict) -> dict:
    if name == "check_account_status":
        return await _tool_check_account_status(db, user_tg_id)
    if name == "escalate_to_human":
        return {"ok": True, "reason": args.get("reason", "")}
    return {"error": f"ابزار ناشناخته: {name}"}


def _build_client(db):
    # ایمپورت تنبل (lazy) تا اگر کتابخانه‌ی google-genai نصب نبود، بقیه‌ی بات
    # (که ربطی به دستیار هوشمند ندارد) بدون خطا بالا بیاید.
    from google import genai
    return genai.Client(api_key=resolve_gemini_key(db))


def _history_to_contents(history, user_message: str):
    from google.genai import types

    contents = []
    for row in history:
        role = "model" if row["role"] == "model" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=row["message"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))
    return contents


async def get_reply(db, user_tg_id: int, history: list, user_message: str) -> dict:
    """یک نوبت کامل گفتگو با دستیار را اجرا می‌کند (شامل چند دور tool-calling
    در صورت نیاز خودِ مدل).

    history: خروجی db.get_ai_conversation(user_id) - لیستی از ردیف‌های
        sqlite3.Row با کلیدهای role ('user'/'model') و message.
    خروجی: {"reply": متن نهایی برای نمایش به کاربر, "escalate": bool}
    """
    if not is_configured(db):
        return {
            "reply": "دستیار هوشمند در حال حاضر تنظیم نشده. پیامت مستقیم برای پشتیبانی ارسال می‌شود.",
            "escalate": True,
        }

    try:
        from google.genai import types
    except ImportError:
        _log.error("کتابخانه‌ی google-genai نصب نیست؛ pip install google-genai را روی سرور اجرا کن.")
        return {
            "reply": "دستیار هوشمند موقتاً در دسترس نیست. پیامت مستقیم برای پشتیبانی ارسال می‌شود.",
            "escalate": True,
        }

    faq = await asyncio.to_thread(db.build_ai_faq_text)
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(faq=faq)

    contents = _history_to_contents(history, user_message)
    tool = types.Tool(function_declarations=_TOOLS)
    gen_config = types.GenerateContentConfig(system_instruction=system_prompt, tools=[tool])

    client = _build_client(db)
    escalate = False
    reply_text = ""

    try:
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=config.AI_SUPPORT_MODEL,
                contents=contents,
                config=gen_config,
            )
            candidate = response.candidates[0]
            parts = candidate.content.parts or []
            function_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

            if not function_calls:
                reply_text = "".join(p.text for p in parts if getattr(p, "text", None)).strip()
                break

            # نوبت مدل (شامل درخواست ابزار) را به تاریخچه اضافه کن، بعد
            # نتیجه‌ی هر ابزار را به‌عنوان پاسخ برگردان تا مدل دور بعد را
            # با اطلاعات واقعی ادامه بدهد.
            contents.append(candidate.content)
            for fc in function_calls:
                if fc.name == "escalate_to_human":
                    escalate = True
                result = await _run_tool(db, user_tg_id, fc.name, dict(fc.args or {}))
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_function_response(name=fc.name, response=result)],
                    )
                )
            if escalate:
                # نیازی نیست بعد از escalate دوباره از مدل جواب بخواهیم؛ متن
                # مناسب برای این حالت پایین‌تر یکسان تنظیم می‌شود.
                break
        else:
            reply_text = ""
    except Exception:
        _log.exception("خطا در ارتباط با Gemini API برای کاربر %s.", user_tg_id)
        return {
            "reply": "در ارتباط با دستیار هوشمند مشکلی پیش اومد. پیامت رو برای پشتیبانی انسانی ارسال می‌کنم.",
            "escalate": True,
        }

    if escalate and not reply_text:
        reply_text = "باشه، مکالمه رو به پشتیبانی انسانی وصل می‌کنم؛ لطفاً چند لحظه صبر کن. 🙏"
    if not reply_text:
        reply_text = "متوجه نشدم؛ می‌تونی طور دیگه‌ای توضیح بدی؟"

    return {"reply": reply_text, "escalate": escalate}
