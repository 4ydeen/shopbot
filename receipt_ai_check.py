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

۴) چک‌های ریاضی قطعی (بدون نیاز به قضاوت AI): همزمان با تحلیل تصویری، مدل
   شماره کارت/شبای مقصد و شماره پیگیری/مرجع را عیناً از متن رسید OCR
   می‌کند. روی این دو مقدار خام، دو چک کاملاً مستقل از AI انجام می‌شود:
     - شماره کارت باید الگوریتم Luhn را رد کند و پیش‌شماره‌اش (۶ رقم اول)
       باید متعلق به یک بانک واقعی ایرانی باشد؛ شبا هم باید چک‌سام
       استاندارد IBAN (ISO 7064) را پاس کند. این‌ها استانداردهای واقعی
       بانکی هستند، نه حدس - یک عدد سرهم‌بندی‌شده تقریباً همیشه رد می‌شود.
     - شماره پیگیری/مرجع متن رسید در جدول receipt_hashes ذخیره و برای
       رسید تکراری چک می‌شود - مستقل از هش فایل، پس حتی اگر کاربر عکس را
       کمی ویرایش/فشرده کرده باشد (که هش فایل را عوض می‌کند) باز هم رسید
       ری‌یوزشده لو می‌رود.
   نکته‌ی مهم: این چک‌ها فقط زمانی اجرا می‌شوند که مقدار کاملاً خوانا و
   بدون ستاره باشد (شماره‌های ماسک‌شده اصلاً بررسی نمی‌شوند) و شکست‌شان
   هرگز به‌تنهایی reject خودکار ایجاد نمی‌کند (فقط note برای ادمین) - چون
   امکان اشتباه OCR روی یک رقم وجود دارد؛ فقط تکراربودن شماره مرجع مثل
   تکراربودن هش، به شرط روشن‌بودن auto-reject، خودکار رد می‌شود.
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

علاوه بر این دو مقدار خام را هم دقیقاً همان‌طور که در عکس نوشته شده (بدون
فاصله، بدون خط‌تیره، فقط رقم/حروف انگلیسی) استخراج کن - این دو فیلد صرفاً
OCR هستند، قضاوتی درباره‌شان نکن:
- شماره کارت یا شبای مقصد که داخل خودِ متن رسید چاپ شده (همانی که رسید ادعا
  می‌کند پول به آن واریز شده)، اگر بخشی از آن با ستاره پوشانده شده رقم‌های
  ستاره‌دار را هم به همان شکل با کاراکتر * بگذار.
- شماره پیگیری/مرجع/سند تراکنش (هرکدام که در رسید هست).
اگر هرکدام خوانده نشد یا وجود نداشت، رشته خالی "" بگذار.

فقط یک JSON خام و بدون هیچ توضیح اضافه یا Markdown، دقیقاً با این فرمت برگردان:
{{"suspicious": true/false, "confidence": "low"/"high", "reasons": ["دلیل کوتاه فارسی", ...], "card_number_digits": "...", "reference_number": "..."}}

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
اگر چیز غیرعادی ندیدی: {{"suspicious": false, "confidence": "low", "reasons": [], "card_number_digits": "...", "reference_number": "..."}}"""


# پیش‌شماره‌های (BIN) ۶ رقمی کارت‌های بانکی ایران که واقعاً توسط بانک/موسسه‌ی
# مالی صادر شده‌اند. منبع: فهرست عمومی و شناخته‌شده‌ی پیش‌شماره‌های شاپرک
# (همانی که در کتابخانه‌های متن‌باز validation کارت ایرانی هم استفاده می‌شود).
# استفاده: اگر شماره کارتی که از متن رسید OCR شده با هیچ‌کدام از این پیش‌شماره‌ها
# شروع نشود، یعنی اصلاً برای یک کارت بانکی واقعی ایرانی صادر نشده - نشانه‌ی
# قوی جعلی بودن رسید (نه صرفاً یک ابهام OCR).
IRAN_CARD_BINS = {
    "603799", "603770", "603769", "610433", "991975", "589463", "589210",
    "621986", "622106", "627353", "585983", "627412", "627488", "627648",
    "627760", "627884", "627961", "628023", "639346", "639347", "639607",
    "606373", "639217", "502908", "628157", "502229", "502806", "636214",
    "207177", "636795", "505785", "504172", "621500", "627381", "505416",
}


def _luhn_valid(digits: str) -> bool:
    """الگوریتم استاندارد Luhn که همه‌ی کارت‌های بانکی (ایران و بین‌المللی)
    باید رعایت کنند. یک عدد تصادفی که کسی سرهم‌بندی کرده باشد، با احتمال
    ۹۰٪ این چک را رد می‌شود."""
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_valid(iban: str) -> bool:
    """چک‌سام استاندارد بین‌المللی IBAN/شبا (ISO 7064 MOD 97-10). هر شبای
    واقعی - از هر بانکی - باید در این چک صدق کند؛ یک شبای دست‌ساز/جعلی با
    احتمال ~۹۷٪ رد می‌شود."""
    iban = iban.replace(" ", "").upper()
    if len(iban) != 26 or not iban.startswith("IR") or not iban[2:].isdigit():
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def _check_extracted_number(raw: str) -> str | None:
    """شماره کارت/شبایی که مدل تصویری از متن رسید خوانده را با چک‌های
    قطعی (نه AI) صحت‌سنجی می‌کند. اگر عدد ستاره‌دار/ناقص باشد (یعنی خودِ
    اپ بانکی بخشی از آن را ماسک کرده - رفتار عادی برای شماره کارت مبدا)
    اصلاً بررسی نمی‌شود، چون داده‌ی کافی برای چک‌سام وجود ندارد. خروجی:
    None یعنی چیزی برای گزارش نیست، در غیر این صورت متن هشدار فارسی."""
    if not raw or "*" in raw:
        return None
    digits = raw.replace(" ", "").replace("-", "")
    if digits.upper().startswith("IR"):
        if not _iban_valid(digits):
            return "⚠️ شماره شبای داخل متن رسید چک‌سام استاندارد IBAN را رد می‌کند (با هیچ حساب بانکی واقعی مطابقت ندارد)"
        return None
    if len(digits) == 16 and digits.isdigit():
        if digits[:6] not in IRAN_CARD_BINS:
            return "⚠️ شماره کارت داخل متن رسید با پیش‌شماره‌ی هیچ بانک ایرانی شناخته‌شده‌ای مطابقت ندارد"
        if not _luhn_valid(digits):
            return "⚠️ شماره کارت داخل متن رسید الگوریتم استاندارد کارت‌های بانکی (Luhn) را رد می‌کند - عدد واقعی نیست"
        return None
    return None


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
            "card_number_digits": str(data.get("card_number_digits") or "").strip(),
            "reference_number": str(data.get("reference_number") or "").strip(),
        }
    except Exception:
        return {"suspicious": False, "confidence": "low", "reasons": [], "card_number_digits": "", "reference_number": ""}


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

    reference_number = ""
    if ai_enabled and can_analyze:
        try:
            verdict = await _run_vision_check(db, image_bytes, mime_type, amount_toman, card_number, card_holder)
            reference_number = verdict.get("reference_number") or ""

            if verdict.get("suspicious") and verdict.get("reasons"):
                note = "🤖 هشدار هوش مصنوعی: " + "؛ ".join(verdict["reasons"])
                reasons.append(note)
                if auto_reject_enabled and verdict.get("confidence") == "high":
                    reject_reasons.append(note)

            # چک قطعی (بدون AI، فقط ریاضی) روی شماره کارت/شبایی که مدل از
            # متن رسید خوانده - مستقل از قضاوت خودِ مدل درباره‌ی suspicious
            # بودن، چون این یک الگوریتم چک‌سام واقعی است نه یک حدس.
            structural_note = _check_extracted_number(verdict.get("card_number_digits") or "")
            if structural_note:
                reasons.append(structural_note)

            # رسید تکراری بر اساس شماره پیگیری/مرجع متن رسید - این حتی وقتی
            # کاربر عکس را کراپ/فشرده/کمی ویرایش کرده (و در نتیجه هش فایل
            # عوض شده) هم رسید ری‌یوزشده را لو می‌دهد، چون شماره پیگیری
            # بانکی که داخل متن چاپ شده تغییر نمی‌کند.
            try:
                ref_dup = await asyncio.to_thread(db.find_receipt_ref_reuse, reference_number, ref_kind, ref_id)
                if ref_dup:
                    other_kind = "سفارش" if ref_dup["ref_kind"] == "order" else "شارژ کیف پول"
                    ref_dup_reason = (
                        f"⛔️ شماره پیگیری/مرجع «{reference_number}» قبلاً هم برای "
                        f"{other_kind} #{ref_dup['ref_id']} ثبت شده بود (رسید تکراری با عکس متفاوت)"
                    )
                    reasons.append(ref_dup_reason)
                    if auto_reject_enabled:
                        reject_reasons.append(ref_dup_reason)
            except Exception as exc:
                _log.warning("receipt_ai_check: بررسی تکراری‌بودن شماره مرجع خطا داد: %s", exc)
        except Exception as exc:
            _log.warning("receipt_ai_check: بررسی AI ناموفق بود: %s", exc)
            available = False

    try:
        await asyncio.to_thread(db.record_receipt_hash, file_hash, ref_kind, ref_id, reference_number)
    except Exception as exc:
        _log.warning("receipt_ai_check: ثبت هش/شماره مرجع رسید خطا داد: %s", exc)

    return {
        "note": "\n".join(reasons) if reasons else None,
        "available": available,
        "reject": bool(reject_reasons),
        "reject_reason": "\n".join(reject_reasons) if reject_reasons else None,
    }
