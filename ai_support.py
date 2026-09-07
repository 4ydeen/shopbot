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
  - این ماژول هیچ عملیات نوشتنی/مالی مستقیم (رفاند، تمدید، تغییر دیتابیس،
    تخفیف، کسر از کیف پول) انجام نمی‌دهد. تنها «نوشتن» مجاز، ابزار
    show_purchase_options است که چیزی را در دیتابیس تغییر نمی‌دهد؛ فقط همان
    کارتِ خریدِ واقعی (با قیمت زنده، اعمال خودکار کیف پول و دکمه‌های واقعی
    پرداخت) را که کاربر با زدن دکمه‌ی «خرید» هم می‌بیند، زودتر به او نشان
    می‌دهد. تسویه‌ی نهایی همیشه با تاییدِ خودِ کاربر روی همان دکمه‌ها انجام
    می‌شود - نه با تصمیم مدل.
  - هر وقت موضوع مالی/شکایت/رفاند بود یا کاربر صراحتاً خواست، مکالمه با ابزار
    escalate_to_human به پشتیبانی انسانی ارجاع داده می‌شود.

اگر هیچ کلید API (نه از پنل بات، نه از .env) تنظیم نشده باشد، get_reply()
بدون تلاش برای اتصال به API بلافاصله escalate=True برمی‌گرداند تا کاربر
معطل نماند. کلید API از داخل پنل ادمین بات (دستیار هوشمند → تنظیم کلید API)
هم قابل تنظیم است - در آن صورت نیازی به .env یا ری‌استارت سرور نیست.
"""

import asyncio
import logging
import json
from datetime import datetime, timezone

import aiohttp

import config
from sub_info import fetch_sub_info
from jalali import to_jalali_str
from panel_providers import get_provider, PanelError

_log = logging.getLogger("ai_support")

# حداکثر تعداد دوری که مدل مجاز است پشت‌سرهم ابزار صدا بزند، قبل از این‌که
# مجبورش کنیم یک جواب متنی نهایی بدهد (جلوگیری از حلقه‌ی بی‌نهایت تابع‌زنی).
# توجه: هر دور یعنی یک درخواست واقعی و جداگانه به Gemini (و یک واحد از سهمیه‌ی
# روزانه‌ی رایگان مصرف می‌شود). ۳ دور برای اکثر گفتگوها کافی است (مثلاً:
# list_products → show_purchase_options → جواب نهایی) و نسبت به ۴ دور، مصرف
# سهمیه به‌ازای پیام‌های پیچیده را کمی کاهش می‌دهد.
_MAX_TOOL_ROUNDS = 3

# گزینه‌های مدلی که از پنل ادمین قابل انتخاب هستند، به‌همراه توضیح کوتاه درباره‌ی
# سهمیه‌ی رایگان تقریبی‌شان (اعداد رسمی گوگل مدام تغییر می‌کنند؛ این توضیح‌ها
# فقط جهت مقایسه‌ی نسبی مدل‌ها هستند - برای عدد دقیق و زنده به aistudio.google.com
# بخش Usage نگاه کن). ترتیب: از سریع‌ترین/بیشترین سهمیه‌ی رایگان تا باکیفیت‌ترین.
MODEL_CHOICES = [
    ("gemini", "gemini-2.5-flash-lite", "⚡ Gemini Flash-Lite — سریع و اقتصادی برای حجم بالا"),
    ("gemini", "gemini-2.5-flash", "🔷 Gemini Flash — تعادل کیفیت و سرعت"),
    ("gemini", "gemini-2.5-pro", "🎯 Gemini Pro — استدلال قوی‌تر؛ سهمیه/هزینه بیشتر"),
    ("groq", "openai/gpt-oss-20b", "🚀 Groq GPT-OSS 20B — بسیار سریع، مناسب چت روزمره"),
    ("groq", "openai/gpt-oss-120b", "🧠 Groq GPT-OSS 120B — کیفیت بالاتر برای Agent"),
    ("groq", "qwen/qwen3.6-27b", "🛠 Groq Qwen 3.6 27B — ابزار و reasoning قوی"),
    ("openrouter", "openrouter/free", "🆓 OpenRouter Free — روتر مدل‌های رایگان؛ مدل پشت آن ممکن است تغییر کند"),
]

PROVIDER_LABELS = {
    "auto": "🤖 خودکار (Gemini → Groq → OpenRouter)",
    "gemini": "🔷 فقط Gemini",
    "groq": "🚀 فقط Groq",
    "openrouter": "🌐 فقط OpenRouter",
}


def _setting(db, key, default=""):
    return (db.get_setting(key, default) or "").strip()


def resolve_provider_mode(db) -> str:
    mode = _setting(db, "ai_provider", "auto")
    return mode if mode in PROVIDER_LABELS else "auto"


def resolve_gemini_model(db) -> str:
    return _setting(db, "gemini_model", "gemini-2.5-flash-lite") or getattr(config, "AI_SUPPORT_MODEL", "gemini-2.5-flash-lite")


def resolve_groq_model(db) -> str:
    return _setting(db, "groq_model", "openai/gpt-oss-20b")


def resolve_openrouter_model(db) -> str:
    return _setting(db, "openrouter_model", "openrouter/free")


def _split_keys(raw: str) -> list:
    if not raw:
        return []
    parts = raw.replace(",", "\n").splitlines()
    seen, keys = set(), []
    for p in parts:
        k = p.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def resolve_gemini_keys(db) -> list:
    keys = _split_keys(_setting(db, "gemini_api_key"))
    return keys or _split_keys(getattr(config, "GEMINI_API_KEY", ""))


def resolve_groq_keys(db) -> list:
    keys = _split_keys(_setting(db, "groq_api_key"))
    return keys or _split_keys(getattr(config, "GROQ_API_KEY", ""))


def resolve_openrouter_keys(db) -> list:
    keys = _split_keys(_setting(db, "openrouter_api_key"))
    return keys or _split_keys(getattr(config, "OPENROUTER_API_KEY", ""))


def resolve_gemini_key(db) -> str:
    keys = resolve_gemini_keys(db)
    return keys[0] if keys else ""


def resolve_gemini_key_source(db) -> str:
    if _setting(db, "gemini_api_key"):
        return "db"
    if getattr(config, "GEMINI_API_KEY", ""):
        return "env"
    return "none"


def resolve_provider_keys(db, provider: str) -> list:
    return {
        "gemini": resolve_gemini_keys,
        "groq": resolve_groq_keys,
        "openrouter": resolve_openrouter_keys,
    }.get(provider, lambda _db: [])(db)


def configured_providers(db) -> list:
    return [p for p in ("gemini", "groq", "openrouter") if resolve_provider_keys(db, p)]


def is_configured(db) -> bool:
    mode = resolve_provider_mode(db)
    if mode == "auto":
        return bool(configured_providers(db))
    return bool(resolve_provider_keys(db, mode))

_SYSTEM_PROMPT_TEMPLATE = """تو دستیار پشتیبانی فارسی‌زبان یک فروشگاه فروش اشتراک VPN (V2Ray/کانفیگ) هستی.

قوانین اجباری:
۱. فقط بر اساس اطلاعات واقعی که از ابزارها (tools) می‌گیری یا در «دانش پایه» زیر آمده جواب بده. هرگز چیزی را حدس نزن یا وعده‌ی چیزی که مطمئن نیستی نده. قیمت/موجودی/مشخصات محصولات را همیشه با ابزار list_products بگیر؛ هرگز از حافظه یا حدس نگو.
۲. تو خودت هیچ عملیات مالی را نهایی نمی‌کنی: نمی‌توانی رفاند بدهی، سرویس را تمدید کنی، تخفیف بدهی، کانفیگ بسازی یا مستقیماً از کیف پول کسر کنی. اما اگر کاربر خواست چیزی بخرد، اجازه داری با ابزار show_purchase_options همان کارت خرید واقعی (قیمت، اعمال خودکار کیف پول، دکمه‌های پرداخت) را برایش باز کنی تا خودش با زدن دکمه نهایی کند - این کار را دریغ نکن، بخشی از وظیفه‌ی توست که خرید را برای کاربر ساده و کامل کنی. برای رفاند/تمدید/تخفیف دستی/شکایت مالی همچنان باید escalate_to_human را صدا بزنی.
۳. اگر کاربر صراحتاً خواست با انسان صحبت کند، ناراحت/عصبانی بود، یا موضوع شکایت/اختلاف مالی بود، بلافاصله (بدون معطلی و بدون اصرار برای ادامه‌ی گفتگو با تو) escalate_to_human را صدا بزن.
۴. اگر سوال درباره‌ی وضعیت شخصیِ خودِ کاربر است (سرویسش، حجم باقی‌مانده، انقضا، موجودی کیف پول، سفارش‌ها)، همیشه اول ابزار مربوطه را صدا بزن؛ از حافظه یا حدس جواب نده.
۴-۱. برای اینکه سرویس «فعال» یا «غیرفعال» است، فقط و فقط به فیلد panel_status نگاه کن (اگر موجود بود)؛ داشتنِ حجم باقی‌مانده یا نرسیدن تاریخ انقضا به این معنی نیست که سرویس روشن است - ممکن است دستی یا به هر دلیلی روی پنل خاموش شده باشد.
۵. کوتاه، دوستانه و محاوره‌ای فارسی بنویس؛ از ایموجی مناسب (نه زیاد) استفاده کن. از پاراگراف‌های طولانی خودداری کن.
۶. اگر بعد از تلاش نتوانستی مشکل را حل کنی (نه اینکه صرفاً کاربر یک‌بار درخواست انسان نکرده)، صادقانه بگو و escalate_to_human را صدا بزن؛ کاربر را سردرگم نگه نداری. دکمه‌ی «صحبت با پشتیبانی انسانی» از ابتدا در اختیار کاربر نیست - این خودِ توست که باید موقع نیاز واقعی (سوال مالی، شکایت، درخواست صریح کاربر، یا ناتوانی از پاسخ) او را ارجاع بدهی، نه اینکه منتظر بمانی کاربر خودش درخواست کند.
۷. برای سوال درباره‌ی پلن‌ها/قیمت‌ها/دسته‌بندی‌ها/محصولات موجود، ابزار list_products را صدا بزن.
۸. وقتی کاربر تصمیم به خرید محصول مشخصی گرفت (یا از تو خواست کمکش کنی بخرد)، بعد از مشخص‌شدن محصول با list_products، ابزار show_purchase_options را با همان product_id صدا بزن تا کارت خرید واقعی برایش نمایش داده شود.

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
        "name": "list_products",
        "description": (
            "لیست دسته‌بندی‌ها و محصولات (پلن‌های) واقعیِ فعالِ فروشگاه را با "
            "قیمت، مدت، توضیحات و موجودی برمی‌گرداند. برای هر سوالی درباره‌ی "
            "«چه پلنی دارید»، «قیمت‌ها چقدره»، «فرقشون چیه» این ابزار را صدا "
            "بزن؛ هرگز قیمت یا مشخصات را حدس نزن."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "show_purchase_options",
        "description": (
            "همان کارت خریدِ واقعیِ یک محصول (قیمت نهایی، اعمال خودکار کیف "
            "پول، دکمه‌های تعداد/کد تخفیف/ادامه‌ی خرید) را برای کاربر در چت "
            "نمایش می‌دهد - دقیقاً همان چیزی که با زدن دکمه‌ی «خرید» از منو "
            "می‌بیند. هیچ مبلغی را خودش کسر یا نهایی نمی‌کند؛ فقط مسیر خرید "
            "را جلوی کاربر باز می‌کند تا با زدن دکمه‌ی نهایی خودش تکمیلش کند. "
            "فقط بعد از list_products و با product_id واقعی صدا بزن."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": "شناسه‌ی محصول، دقیقاً همان id که در خروجی list_products آمده.",
                }
            },
            "required": ["product_id"],
        },
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


def _split_keys(raw: str) -> list:
    """یک رشته را (که ممکن است چند کلید API با خط جدید/کاما/فاصله از هم جدا
    شده باشند) به لیست کلیدهای یکتا و پاک‌شده تبدیل می‌کند."""
    if not raw:
        return []
    parts = raw.replace(",", "\n").splitlines()
    seen = set()
    keys = []
    for p in parts:
        k = p.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def resolve_gemini_keys(db) -> list:
    """لیست کلیدهای API Gemini را برمی‌گرداند (پشتیبانی از چند کلید برای
    چرخش خودکار هنگام برخورد با خطای سهمیه/429). اولویت با کلید(های)ی است
    که ادمین از داخل پنل بات تنظیم کرده؛ اگر خالی بود، کلید سراسری .env."""
    keys = _split_keys(db.get_setting("gemini_api_key", ""))
    if keys:
        return keys
    return _split_keys(config.GEMINI_API_KEY)


def resolve_gemini_key(db) -> str:
    """اولین کلید API تنظیم‌شده را برمی‌گرداند (سازگاری با کدهای قبلی)."""
    keys = resolve_gemini_keys(db)
    return keys[0] if keys else ""


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
    return bool(resolve_gemini_keys(db))


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


async def _tool_list_products(db) -> dict:
    def _read():
        categories = db.get_categories(active_only=True)
        out = []
        for cat in categories:
            products = db.get_products(cat["id"], active_only=True)
            items = []
            for p in products:
                stock = db.count_available_configs(p["id"]) if not p["is_auto_provision"] else None
                items.append({
                    "product_id": p["id"],
                    "name": p["name"],
                    "price_toman": p["price"],
                    "duration_days": p["duration_days"],
                    "description": p["description"] or "",
                    "in_stock": True if p["is_auto_provision"] else stock > 0,
                    "stock_count": "نامحدود (آنی)" if p["is_auto_provision"] else stock,
                })
            if items:
                out.append({"category": cat["name"], "products": items})
        return out

    categories = await asyncio.to_thread(_read)
    if not categories:
        return {"categories": [], "note": "در حال حاضر هیچ محصول فعالی در فروشگاه ثبت نشده."}
    return {"categories": categories}


async def _tool_show_purchase_options(db, args: dict) -> dict:
    product_id = args.get("product_id")
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return {"error": "product_id نامعتبر است."}
    product = await asyncio.to_thread(db.get_product, product_id)
    if not product or not product["is_active"]:
        return {"error": "محصولی با این شناسه پیدا نشد یا غیرفعال است. اول list_products را صدا بزن."}
    return {"ok": True, "product_id": product_id, "name": product["name"]}


async def _run_tool(db, user_tg_id: int, name: str, args: dict) -> dict:
    if name == "check_account_status":
        return await _tool_check_account_status(db, user_tg_id)
    if name == "list_products":
        return await _tool_list_products(db)
    if name == "show_purchase_options":
        return await _tool_show_purchase_options(db, args)
    if name == "escalate_to_human":
        return {"ok": True, "reason": args.get("reason", "")}
    return {"error": f"ابزار ناشناخته: {name}"}


def _build_client(api_key: str):
    from google import genai
    return genai.Client(api_key=api_key)


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (408, 409, 429, 500, 502, 503, 504):
        return True
    text = str(exc).upper()
    return any(x in text for x in ("429", "RESOURCE_EXHAUSTED", "RATE LIMIT", "TIMEOUT", "503", "502"))


def _history_to_contents(history, user_message: str):
    from google.genai import types
    contents = []
    for row in history:
        role = "model" if row["role"] == "model" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=row["message"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))
    return contents


def _openai_tools():
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in _TOOLS]


def _history_to_openai(history, user_message: str, system_prompt: str):
    messages = [{"role": "system", "content": system_prompt}]
    for row in history:
        messages.append({"role": "assistant" if row["role"] == "model" else "user", "content": row["message"]})
    messages.append({"role": "user", "content": user_message})
    return messages


async def _openai_chat(provider: str, api_key: str, model: str, messages: list):
    url = "https://api.groq.com/openai/v1/chat/completions" if provider == "groq" else "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://telegram.org/"
        headers["X-Title"] = "ShopVPN AI Support"
    payload = {
        "model": model,
        "messages": messages,
        "tools": _openai_tools(),
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    timeout = aiohttp.ClientTimeout(total=75)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"{provider} HTTP {resp.status}: {body[:600]}")
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{provider} پاسخ JSON نامعتبر داد") from exc


async def _run_gemini(db, user_tg_id: int, history: list, user_message: str, system_prompt: str):
    from google.genai import types
    api_keys = resolve_gemini_keys(db)
    if not api_keys:
        raise RuntimeError("Gemini API key تنظیم نشده")
    contents = _history_to_contents(history, user_message)
    tool = types.Tool(function_declarations=_TOOLS)
    gen_config = types.GenerateContentConfig(system_instruction=system_prompt, tools=[tool])
    model_name = resolve_gemini_model(db)
    last_exc = None
    for api_key in api_keys:
        client = _build_client(api_key)
        try:
            escalate, ui_action = False, None
            for _ in range(_MAX_TOOL_ROUNDS):
                response = await asyncio.to_thread(client.models.generate_content, model=model_name, contents=contents, config=gen_config)
                candidate = response.candidates[0]
                parts = candidate.content.parts or []
                calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
                if not calls:
                    text = "".join(p.text for p in parts if getattr(p, "text", None)).strip()
                    return {"reply": text, "escalate": escalate, "ui_action": ui_action}
                contents.append(candidate.content)
                for fc in calls:
                    if fc.name == "escalate_to_human":
                        escalate = True
                    result = await _run_tool(db, user_tg_id, fc.name, dict(fc.args or {}))
                    if fc.name == "show_purchase_options" and result.get("ok"):
                        ui_action = {"type": "show_product", "product_id": result["product_id"]}
                    contents.append(types.Content(role="user", parts=[types.Part.from_function_response(name=fc.name, response=result)]))
                if escalate:
                    return {"reply": "باشه، مکالمه رو به پشتیبانی انسانی وصل می‌کنم؛ لطفاً چند لحظه صبر کن. 🙏", "escalate": True, "ui_action": ui_action}
            return {"reply": "متوجه شدم؛ برای اینکه جواب اشتباه ندم، این مورد رو به پشتیبانی انسانی می‌سپارم.", "escalate": True, "ui_action": ui_action}
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc):
                raise
            _log.warning("Gemini key failed; rotating key/provider: %s", exc)
    raise last_exc or RuntimeError("Gemini failed")


async def _run_openai_compatible(db, user_tg_id: int, history: list, user_message: str, system_prompt: str, provider: str):
    keys = resolve_provider_keys(db, provider)
    if not keys:
        raise RuntimeError(f"{provider} API key تنظیم نشده")
    model = resolve_groq_model(db) if provider == "groq" else resolve_openrouter_model(db)
    base_messages = _history_to_openai(history, user_message, system_prompt)
    last_exc = None
    for api_key in keys:
        messages = list(base_messages)
        try:
            ui_action = None
            for _ in range(_MAX_TOOL_ROUNDS):
                data = await _openai_chat(provider, api_key, model, messages)
                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                tool_calls = msg.get("tool_calls") or []
                content = msg.get("content") or ""
                if not tool_calls:
                    return {"reply": content.strip(), "escalate": False, "ui_action": ui_action}
                assistant_msg = {"role": "assistant", "content": content, "tool_calls": tool_calls}
                messages.append(assistant_msg)
                escalate = False
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    if name == "escalate_to_human":
                        escalate = True
                    result = await _run_tool(db, user_tg_id, name, args)
                    if name == "show_purchase_options" and result.get("ok"):
                        ui_action = {"type": "show_product", "product_id": result["product_id"]}
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": json.dumps(result, ensure_ascii=False)})
                if escalate:
                    return {"reply": "باشه، مکالمه رو به پشتیبانی انسانی وصل می‌کنم؛ لطفاً چند لحظه صبر کن. 🙏", "escalate": True, "ui_action": ui_action}
            return {"reply": "برای اینکه جواب اشتباه ندم، این مورد رو به پشتیبانی انسانی می‌سپارم.", "escalate": True, "ui_action": ui_action}
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc):
                raise
            _log.warning("%s key failed; rotating key: %s", provider, exc)
    raise last_exc or RuntimeError(f"{provider} failed")


async def get_reply(db, user_tg_id: int, history: list, user_message: str) -> dict:
    """Agent چند-Provider: Gemini، Groq و OpenRouter با چرخش کلید و fallback."""
    if not is_configured(db):
        return {"reply": "دستیار هوشمند در حال حاضر تنظیم نشده. پیامت مستقیم برای پشتیبانی ارسال می‌شود.", "escalate": True}
    faq = await asyncio.to_thread(db.build_ai_faq_text)
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(faq=faq)
    mode = resolve_provider_mode(db)
    providers = configured_providers(db) if mode == "auto" else [mode]
    last_exc = None
    for provider in providers:
        try:
            if provider == "gemini":
                result = await _run_gemini(db, user_tg_id, history, user_message, system_prompt)
            else:
                result = await _run_openai_compatible(db, user_tg_id, history, user_message, system_prompt, provider)
            if result.get("reply"):
                return result
            raise RuntimeError(f"{provider} پاسخ خالی داد")
        except Exception as exc:
            last_exc = exc
            _log.exception("AI provider %s failed; trying fallback if configured.", provider)
            continue
    _log.error("All AI providers failed: %s", last_exc)
    return {"reply": "در حال حاضر سرویس هوش مصنوعی در دسترس نیست؛ پیامت رو برای پشتیبانی انسانی می‌فرستم.", "escalate": True}

