# -*- coding: utf-8 -*-
"""
تشخیص رسید جعلی/تکراری کارت‌به‌کارت با هوش مصنوعی.

این ماژول عکس/فایل رسیدی که کاربر برای پرداخت کارت‌به‌کارت دستی می‌فرستد را،
پیش از رسیدن به گروه/چت ادمین، از دو مسیر مستقل بررسی می‌کند:

  ۱) رسید تکراری: هش (sha256) فایل رسید در جدول receipt_hashes ذخیره می‌شود؛
     اگر همان فایل قبلاً برای سفارش/شارژ دیگری استفاده شده باشد - رایج‌ترین
     الگوی تقلب، یعنی ری‌یوز یک رسید تاییدشده‌ی قدیمی برای خرید جدید - بدون
     نیاز به هیچ فراخوانی هوش مصنوعی و با قطعیت کامل تشخیص داده می‌شود.

  ۲) تحلیل تصویر با مدل چندوجهی: از همان زیرساخت چندمدلی «دستیار هوشمند»
     (ai_support.py) استفاده می‌شود - فعلاً فقط Gemini، چون تنها گزینه‌ی
     چندوجهیِ پیکربندی‌شده در پروژه است. مبلغ/کارت مقصد داخل عکس با فاکتور
     تطبیق داده می‌شود و نشانه‌های دستکاری بصری بررسی می‌شوند.

این ماژول به‌طور پیش‌فرض هرگز خودش سفارشی را رد نمی‌کند - فقط یک یادداشت
هشدار کوتاه فارسی برمی‌گرداند که به پیام ادمین اضافه می‌شود؛ تصمیم نهایی دست
ادمین است. اگر سرویس AI در دسترس نبود/خطا داد (یا اصلاً کلیدی تنظیم نشده)،
available=False برمی‌گردد تا پیام ادمین به‌جای ساکت‌ماندن، صریحاً بگوید بررسی
AI انجام نشد - نه اینکه به‌اشتباه به‌نظر برسد رسید «تایید» شده.

۳) رد خودکار رسید بسیار مشکوک: اگر تنظیم "receipt_ai_auto_reject_enabled"
   روشن باشد (پیش‌فرض روشن)، دو حالت به‌صورت خودکار سفارش/شارژ را رد می‌کنند
   (بدون نیاز به تایید ادمین) و به کاربر پیام می‌دهند که رسیدش رد شده و با
   پشتیبانی تماس بگیرد: یکی رسید تکراری/ری‌یوزشده (قطعیت کامل، بدون نیاز به
   AI)، دیگری وقتی مدل تصویری رسید را "suspicious" با درجه اطمینان "high"
   تشخیص دهد (یعنی مدل تقریباً مطمئن است رسید جعلی/دستکاری‌شده یا کاملاً با
   فاکتور مغایر است - نه فقط یک ابهام جزئی). خروجی check_receipt در این
   حالت‌ها reject=True و reject_reason را هم برمی‌گرداند. با خاموش‌کردن این
   تنظیم، رفتار قبلی (فقط هشدار به ادمین، بدون رد خودکار) برقرار می‌ماند.
   کل قابلیت بررسی AI هم با تنظیم "receipt_ai_check_enabled" کاملاً
   قابل خاموش/روشن شدن است.
"""

import asyncio
import hashlib
import json
import logging

import ai_support

_log = logging.getLogger("receipt_ai_check")

_PROMPT = """شما دستیار تشخیص تقلب در رسیدهای بانکی کارت‌به‌کارت ایران هستید.
تصویر/فایل رسید پرداخت پیوست‌شده را با اطلاعات فاکتور زیر مقایسه کن:

مبلغ مورد انتظار (تومان): {amount}
شماره کارت مقصد مورد انتظار: {card_number}
نام صاحب کارت مقصد مورد انتظار: {card_holder}

نکاتی که باید بررسی کنی:
- آیا مبلغ داخل رسید دقیقاً با مبلغ مورد انتظار یکی است؟
- آیا شماره کارت/نام مقصد داخل رسید با مقادیر بالا مطابقت دارد؟ (تطبیق تقریبی چند رقم آخر کافی است، فونت‌های بانکی گاهی ناخوانا هستند)
- آیا نشانه‌ی دستکاری دیجیتال دیده می‌شود (فونت/رنگ/فاصله‌گذاری نامنظم در عدد مبلغ، پیکسل‌خوردگی موضعی دور یک عدد، چیدمانی که با اپ‌های بانکی واقعی ایران همخوانی ندارد، عکس از عکسِ یک اسکرین‌شات)؟
- آیا تاریخ/ساعت تراکنش داخل رسید منطقی و معقول به‌نظر می‌رسد (نه خیلی قدیمی نسبت به الان)؟

فقط یک JSON خام و بدون هیچ توضیح اضافه یا Markdown، دقیقاً با این فرمت برگردان:
{{"suspicious": true/false, "confidence": "low"/"high", "reasons": ["دلیل کوتاه فارسی", ...]}}

راهنمای فیلد confidence - خیلی مهم، محتاط باش:
- "high" را فقط وقتی بگذار که تقریباً مطمئنی رسید جعلی/دستکاری‌شده است، یا
  مبلغ/شماره کارت به‌طور کامل و آشکار با مقادیر بالا مغایرت دارد (نه صرفاً
  چند رقم آخر ناخوانا یا کیفیت پایین عکس). وقتی suspicious=true و
  confidence="high" باشد، این رسید به‌صورت کاملاً خودکار و بدون هیچ بررسی
  انسانی رد خواهد شد - پس این مقدار را فقط در موارد کاملاً واضح و بدون شک
  انتخاب کن.
- در هر حالت نامطمئن، مبهم، یا با شواهد ضعیف (کیفیت پایین عکس، فونت کمی
  متفاوت، عدم قطعیت در تطبیق چند رقم کارت، زاویه/نور بد) حتماً "low" بگذار -
  این موارد فقط به‌صورت هشدار به ادمین نمایش داده می‌شود و تصمیم نهایی با
  خود ادمین می‌ماند.
اگر چیز غیرعادی ندیدی: {{"suspicious": false, "confidence": "low", "reasons": []}}"""


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _download(bot, file_id: str) -> bytes:
    tg_file = await bot.get_file(file_id)
    buf = await bot.download_file(tg_file.file_path)
    return buf.read() if hasattr(buf, "read") else bytes(buf)


def _guess_mime(receipt_type: str, message=None) -> str:
    if receipt_type == "document" and message is not None:
        doc = getattr(message, "document", None)
        mt = getattr(doc, "mime_type", None) if doc else None
        if mt:
            return mt
    return "image/jpeg"


def _parse_verdict(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
        confidence = str(data.get("confidence") or "low").strip().lower()
        if confidence not in ("low", "high"):
            confidence = "low"
        return {
            "suspicious": bool(data.get("suspicious")),
            "confidence": confidence,
            "reasons": [str(r).strip() for r in (data.get("reasons") or []) if str(r).strip()],
        }
    except Exception:
        return {"suspicious": False, "confidence": "low", "reasons": []}


async def _run_vision_check(db, image_bytes: bytes, mime_type: str, amount_toman, card_number, card_holder) -> dict:
    """فقط تحلیل تصویری با AI - جدا از چک رسید تکراری. در صورت هر خطایی
    استثنا پرتاب می‌کند تا caller بفهمد available=False است (کلیدها/پروایدر
    و منطق rotate دقیقاً همان چیزی است که ai_support._run_gemini استفاده
    می‌کند تا تنظیمات پنل ادمین یکسان برای هر دو کاربرد به‌کار برود)."""
    from google.genai import types

    api_keys = ai_support.resolve_gemini_keys(db)
    if not api_keys:
        raise RuntimeError("gemini_api_key تنظیم نشده")

    model_name = ai_support.resolve_gemini_model(db)
    prompt = _PROMPT.format(
        amount=f"{amount_toman:,}" if amount_toman else "نامشخص",
        card_number=card_number or "نامشخص",
        card_holder=card_holder or "نامشخص",
    )
    contents = [types.Content(role="user", parts=[
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        types.Part(text=prompt),
    ])]
    gen_config = types.GenerateContentConfig(response_mime_type="application/json")

    last_exc = None
    for api_key in api_keys:
        client = ai_support._build_client(api_key)
        try:
            response = await asyncio.to_thread(
                client.models.generate_content, model=model_name, contents=contents, config=gen_config,
            )
            text = getattr(response, "text", None)
            if not text:
                parts = response.candidates[0].content.parts or []
                text = "".join(p.text for p in parts if getattr(p, "text", None))
            return _parse_verdict(text)
        except Exception as exc:
            last_exc = exc
            if not ai_support._is_retryable(exc):
                raise
            _log.warning("receipt_ai_check: کلید Gemini شکست خورد، رفتن سراغ کلید بعدی: %s", exc)
    raise last_exc or RuntimeError("Gemini failed")


async def check_receipt(bot, db, *, file_id: str, receipt_type: str, ref_kind: str, ref_id: int,
                         amount_toman=None, card_number=None, card_holder=None, message=None) -> dict:
    """بررسی کامل یک رسید تازه‌ارسال‌شده.

    ref_kind/ref_id: نوع و شناسه‌ی رکوردی که این رسید برایش ارسال شده - مثلاً
    ("order", 123) یا ("topup", 45) - برای تشخیص رسید تکراری بین انواع مختلف.

    خروجی: {"note": str|None, "available": bool, "reject": bool, "reject_reason": str|None}
    - note: متن هشدار کوتاه فارسی برای اضافه‌شدن به پیام ادمین (None یعنی
      چیز مشکوکی پیدا نشد).
    - available: آیا بررسی AI واقعاً انجام شد یا نه. چک رسید تکراری همیشه
      مستقل از این انجام می‌شود و در صورت پیدا شدن، در note لحاظ می‌شود -
      even اگر available=False باشد.
    - reject: آیا این رسید آنقدر مشکوک بود که باید به‌صورت خودکار (بدون
      بررسی ادمین) رد شود. فقط وقتی True می‌شود که تنظیم
      "receipt_ai_auto_reject_enabled" روشن باشد و یا رسید عیناً تکراری/
      ری‌یوزشده باشد، یا مدل تصویری با اطمینان "high" مشکوک تشخیص داده باشد.
    - reject_reason: دلیل(های) کوتاه فارسیِ همان رد خودکار (زیرمجموعه‌ای از
      note)، برای نمایش به کاربر/ادمین."""
    reasons = []
    reject_reasons = []
    available = True

    try:
        image_bytes = await _download(bot, file_id)
    except Exception as exc:
        _log.warning("receipt_ai_check: دانلود فایل رسید ناموفق بود: %s", exc)
        return {"note": None, "available": False, "reject": False, "reject_reason": None}

    auto_reject_enabled = (await asyncio.to_thread(db.get_setting, "receipt_ai_auto_reject_enabled", "1")) != "0"

    file_hash = _hash_bytes(image_bytes)
    try:
        dup = await asyncio.to_thread(db.find_receipt_hash_reuse, file_hash, ref_kind, ref_id)
        await asyncio.to_thread(db.record_receipt_hash, file_hash, ref_kind, ref_id)
        if dup:
            other_kind = "سفارش" if dup["ref_kind"] == "order" else "شارژ کیف پول"
            dup_reason = f"⛔️ این عکس رسید دقیقاً قبلاً هم برای {other_kind} #{dup['ref_id']} ارسال شده بود (رسید تکراری/ری‌یوز شده)"
            reasons.append(dup_reason)
            if auto_reject_enabled:
                reject_reasons.append(dup_reason)
    except Exception as exc:
        _log.warning("receipt_ai_check: بررسی رسید تکراری خطا داد: %s", exc)

    ai_enabled = (await asyncio.to_thread(db.get_setting, "receipt_ai_check_enabled", "1")) != "0"
    mime_type = _guess_mime(receipt_type, message)
    can_analyze = mime_type.startswith("image/") or mime_type == "application/pdf"

    if ai_enabled and can_analyze:
        try:
            verdict = await _run_vision_check(db, image_bytes, mime_type, amount_toman, card_number, card_holder)
            if verdict.get("suspicious") and verdict.get("reasons"):
                note = "🤖 هشدار هوش مصنوعی: " + "؛ ".join(verdict["reasons"])
                reasons.append(note)
                if auto_reject_enabled and verdict.get("confidence") == "high":
                    reject_reasons.append(note)
        except Exception as exc:
            _log.warning("receipt_ai_check: بررسی AI ناموفق بود: %s", exc)
            available = False

    return {
        "note": "\n".join(reasons) if reasons else None,
        "available": available,
        "reject": bool(reject_reasons),
        "reject_reason": "\n".join(reject_reasons) if reject_reasons else None,
    }
