# -*- coding: utf-8 -*-
"""
تشخیص رسید جعلی/تکراری کارت‌به‌کارت با هوش مصنوعی.

این ماژول عکس/فایل رسیدی که کاربر برای پرداخت کارت‌به‌کارت دستی می‌فرستد را،
پیش از رسیدن به گروه/چت ادمین، از چند مسیر مستقل بررسی می‌کند:

  ۱) رسید تکراری (هش دقیق فایل): هش (sha256) فایل رسید در جدول
     receipt_hashes ذخیره می‌شود؛ اگر همان فایل قبلاً برای سفارش/شارژ دیگری
     استفاده شده باشد - رایج‌ترین الگوی تقلب - بدون نیاز به هیچ فراخوانی
     هوش مصنوعی و با قطعیت کامل تشخیص داده می‌شود.

  ۲) رسید تکراری با کیفیت/برش متفاوت (هش ادراکی/phash): هش دقیق فایل با
     کوچک‌ترین فشرده‌سازی یا کراپ مجدد کاملاً عوض می‌شود. یک هش ادراکی
     (dHash ۶۴ بیتی، فقط با Pillow، بدون کتابخانه‌ی جانبی) هم از تصویر
     ساخته و ذخیره می‌شود تا رسیدی که کاربر کمی ویرایش/فشرده کرده و دوباره
     برای خرید دیگری فرستاده هم لو برود. این فقط «هشدار» تولید می‌کند (هرگز
     رد خودکار) چون رسیدهای واقعی و متفاوت از یک اپ بانکی می‌توانند ظاهر
     کلی مشابهی داشته باشند و فاصله‌ی همینگ کم لزوماً به‌معنای تکراربودن
     قطعی نیست.

  ۳) تحلیل تصویر با چند مدل چندوجهی مستقل (Gemini + در صورت تنظیم‌بودن
     کلید، Groq و OpenRouter): هر مدلی که کلیدش تنظیم شده باشد به‌صورت
     موازی و مستقل تصویر را تحلیل می‌کند. اگر فقط یک مدل در دسترس باشد،
     رفتار دقیقاً مثل قبل است. اگر چند مدل در دسترس باشند، رد خودکار فقط
     وقتی انجام می‌شود که حداقل دو مدل مستقل هر دو رسید را مشکوک تشخیص
     داده باشند (یکی با اطمینان «high») - نه فقط یکی؛ این یعنی اشتباه یک
     مدل به‌تنهایی دیگر باعث رد خودکار (و آسیب به مشتری واقعی) نمی‌شود، ولی
     وقتی چند مدل مستقل هم‌رای باشند اطمینان تشخیص خیلی بیشتر از قبل است.
     اگر مدل‌ها در استخراج شماره کارت/شماره پیگیری با هم اختلاف داشته باشند
     هم به‌عنوان یک نشانه‌ی ضعیف (نه رد خودکار) به ادمین گزارش می‌شود.
     تنظیم مدل بینایی Groq/OpenRouter مستقل از مدل چت «دستیار هوشمند»
     (ai_support.py) است، چون آن تنظیم برای مدل متنی چت انتخاب می‌شود و
     الزاماً بینایی/تصویر پشتیبانی نمی‌کند؛ اینجا از یک مدل بینایی‌دار ثابت
     برای هرکدام استفاده می‌شود.

این ماژول به‌طور پیش‌فرض هرگز خودش سفارشی را رد نمی‌کند - فقط یک یادداشت
هشدار کوتاه فارسی برمی‌گرداند که به پیام ادمین اضافه می‌شود؛ تصمیم نهایی دست
ادمین است. اگر هیچ‌کدام از سرویس‌های AI در دسترس نبودند/خطا دادند (یا اصلاً
کلیدی تنظیم نشده)، available=False برمی‌گردد تا پیام ادمین به‌جای ساکت‌ماندن،
صریحاً بگوید بررسی AI انجام نشد - نه اینکه به‌اشتباه به‌نظر برسد رسید «تایید»
شده.

۴) رد خودکار رسید بسیار مشکوک: اگر تنظیم "receipt_ai_auto_reject_enabled"
   روشن باشد (پیش‌فرض روشن)، حالت‌های زیر به‌صورت خودکار سفارش/شارژ را رد
   می‌کنند (بدون نیاز به تایید ادمین) و به کاربر پیام می‌دهند که رسیدش رد
   شده و با پشتیبانی تماس بگیرد: رسید تکراری/ری‌یوزشده (هش دقیق یا شماره
   پیگیری، قطعیت کامل، بدون نیاز به AI)، یا وقتی حداقل دو مدل تصویری مستقل
   رسید را مشکوک تشخیص دهند (یکی با اطمینان «high») - نه صرفاً یک مدل به‌تنهایی
   وقتی چند مدل در دسترس بوده‌اند (اگر فقط یک مدل کلید داشته باشد، رفتار
   قبلی/تک‌مدلی برقرار می‌ماند). خروجی check_receipt در این حالت‌ها
   reject=True و reject_reason را هم برمی‌گرداند. با خاموش‌کردن این تنظیم،
   رفتار قبلی (فقط هشدار به ادمین، بدون رد خودکار) برقرار می‌ماند. کل
   قابلیت بررسی AI هم با تنظیم "receipt_ai_check_enabled" کاملاً قابل
   خاموش/روشن شدن است؛ فراخوانی مدل‌های اضافی (Groq/OpenRouter) هم جدا با
   تنظیم "receipt_ai_multi_model_enabled" (پیش‌فرض روشن، فقط وقتی کلید آن
   پروایدرها تنظیم شده باشد اثر دارد) قابل خاموش‌کردن است تا ادمینی که
   نمی‌خواهد سهمیه/هزینه‌ی چند مدل مصرف شود بتواند به همان Gemini تنها
   برگردد.

۵) چک‌های ریاضی قطعی (بدون نیاز به قضاوت AI): همزمان با تحلیل تصویری، مدل
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

۶) تحلیل فرنزیک تصویر (ELA - Error Level Analysis): فقط برای فایل‌های
   JPEG، تصویر با کیفیت ثابت (۹۰) دوباره فشرده و با نسخه‌ی اصلی مقایسه
   می‌شود. اگر یک ناحیه‌ی محدود از عکس نرخ خطای فشرده‌سازی خیلی متفاوتی
   نسبت به بقیه‌ی تصویر داشته باشد، نشانه‌ی احتمالی ویرایش/جای‌گذاری موضعی
   (مثلاً دستکاری روی عدد مبلغ) است - این یک چک کاملاً بدون AI و
   دترمینیستیک است، ولی چون ممکن است هشدار اشتباه هم بدهد (فشرده‌سازی
   چندباره‌ی خودِ تلگرام)، همیشه فقط «note» است، هرگز باعث رد خودکار
   نمی‌شود.
"""

import asyncio
import base64
import hashlib
import io
import json
import logging

import aiohttp

import ai_support

_log = logging.getLogger("receipt_ai_check")

# مدل بینایی‌دار ثابت برای هر پروایدر - مستقل از تنظیم مدل چتِ «دستیار
# هوشمند» (که ممکن است اصلاً بینایی/تصویر پشتیبانی نکند).
_GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
_OPENROUTER_VISION_MODEL = "openrouter/free"

# حداکثر فاصله‌ی همینگ (از ۶۴ بیت) برای این‌که دو تصویر «به‌احتمال زیاد شبیه
# هم» در نظر گرفته شوند. عدد کوچک عمداً محافظه‌کارانه انتخاب شده چون این چک
# فقط note تولید می‌کند، هرگز reject خودکار.
_PHASH_NEAR_DUP_MAX_DISTANCE = 4

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
  confidence="high" باشد، این رسید ممکن است به‌صورت کاملاً خودکار و بدون
  هیچ بررسی انسانی رد شود - پس این مقدار را فقط در موارد کاملاً واضح و
  بدون شک انتخاب کن.
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


def _compute_phash(image_bytes: bytes) -> str | None:
    """هش ادراکی dHash با ۶۴ بیت (فقط Pillow، بدون کتابخانه‌ی جانبی): تصویر
    را به ۹×۸ خاکستری کوچک می‌کند و برای هر پیکسل با پیکسل کناری‌اش مقایسه
    می‌کند. برخلاف sha256، این هش با فشرده‌سازی/تغییر اندازه‌ی جزئی عوض
    نمی‌شود، پس برای تشخیص «همان عکس با کیفیت متفاوت» مناسب است."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("L").resize((9, 8), Image.LANCZOS)
        pixels = list(img.getdata())
        value = 0
        for row in range(8):
            row_pixels = pixels[row * 9:(row + 1) * 9]
            for col in range(8):
                value = (value << 1) | (1 if row_pixels[col] > row_pixels[col + 1] else 0)
        return format(value, "016x")
    except Exception as exc:
        _log.warning("receipt_ai_check: محاسبه‌ی phash ناموفق بود: %s", exc)
        return None


def _hamming_distance_hex(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 64


def _find_near_duplicate(db, phash: "str | None", ref_kind: str, ref_id: int):
    """در بین phashهای رسیدهای قبلی (غیر از همین ref_kind/ref_id) نزدیک‌ترین
    را پیدا می‌کند. فقط برای note - هرگز مبنای رد خودکار نیست."""
    if not phash:
        return None
    try:
        rows = db.find_receipt_phash_candidates(ref_kind, ref_id)
    except Exception as exc:
        _log.warning("receipt_ai_check: خواندن phashهای قبلی خطا داد: %s", exc)
        return None
    best_row, best_dist = None, None
    for row in rows:
        dist = _hamming_distance_hex(phash, row["phash"])
        if dist <= _PHASH_NEAR_DUP_MAX_DISTANCE and (best_dist is None or dist < best_dist):
            best_row, best_dist = row, dist
    return best_row


def _ela_note(image_bytes: bytes, mime_type: str) -> "str | None":
    """Error Level Analysis: فقط برای JPEG. تصویر با کیفیت ثابت دوباره ذخیره
    و با نسخه‌ی اصلی مقایسه می‌شود؛ اگر یک بلوک محدود از عکس نرخ خطای
    فشرده‌سازی به‌مراتب بیشتری از بقیه‌ی تصویر داشته باشد، نشانه‌ی احتمالی
    ویرایش موضعی است. همیشه فقط note - چون ممکن است هشدار اشتباه هم بدهد."""
    if mime_type != "image/jpeg":
        return None
    try:
        from PIL import Image, ImageChops, ImageStat
        orig = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = orig.size
        if w < 60 or h < 60:
            return None
        buf = io.BytesIO()
        orig.save(buf, "JPEG", quality=90)
        buf.seek(0)
        resaved = Image.open(buf).convert("RGB")
        diff = ImageChops.difference(orig, resaved)
        overall_mean = sum(ImageStat.Stat(diff).mean) / 3
        if overall_mean < 1:
            return None
        grid = 8
        bw, bh = max(w // grid, 1), max(h // grid, 1)
        block_means = []
        for gy in range(grid):
            for gx in range(grid):
                box = (gx * bw, gy * bh, min((gx + 1) * bw, w), min((gy + 1) * bh, h))
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                block_means.append(sum(ImageStat.Stat(diff.crop(box)).mean) / 3)
        if not block_means:
            return None
        max_block = max(block_means)
        if max_block > overall_mean * 4 and max_block > 12:
            return ("🔍 تحلیل فرنزیک تصویر (ELA): یک ناحیه‌ی محدود از عکس رسید نرخ خطای "
                    "فشرده‌سازی JPEG بسیار متفاوتی نسبت به بقیه‌ی تصویر دارد - ممکن است نشانه‌ی "
                    "ویرایش/جای‌گذاری دیجیتال موضعی (مثلاً روی عدد مبلغ) باشد؛ ممکن است هشدار "
                    "اشتباه هم باشد، فقط برای بررسی بیشتر ادمین.")
        return None
    except Exception as exc:
        _log.warning("receipt_ai_check: تحلیل ELA خطا داد: %s", exc)
        return None


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


async def _run_gemini_vision(db, image_bytes: bytes, mime_type: str, amount_toman, card_number, card_holder) -> dict:
    """تحلیل تصویری با Gemini - کلیدها/rotate دقیقاً همان چیزی است که
    ai_support._run_gemini استفاده می‌کند تا تنظیمات پنل ادمین یکسان برای
    هر دو کاربرد به‌کار برود."""
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


async def _run_openai_compatible_vision(provider: str, api_keys: list, model: str, prompt: str,
                                         image_bytes: bytes, mime_type: str) -> dict:
    """تحلیل تصویری با هر پروایدر سازگار با OpenAI Chat Completions (Groq،
    OpenRouter) که از content چندبخشی با image_url (data URL) پشتیبانی
    می‌کند."""
    if not api_keys:
        raise RuntimeError(f"{provider} کلید API تنظیم نشده")

    url = "https://api.groq.com/openai/v1/chat/completions" if provider == "groq" else "https://openrouter.ai/api/v1/chat/completions"
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        "temperature": 0.1,
    }
    timeout = aiohttp.ClientTimeout(total=45, connect=10)

    last_exc = None
    for api_key in api_keys:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://telegram.org/"
            headers["X-Title"] = "ShopVPN Receipt AI Check"
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        raise RuntimeError(f"{provider} HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            text = data["choices"][0]["message"]["content"]
            if isinstance(text, list):
                text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
            return _parse_verdict(text)
        except Exception as exc:
            last_exc = exc
            if not ai_support._is_retryable(exc):
                raise
            _log.warning("receipt_ai_check: کلید %s شکست خورد، رفتن سراغ کلید بعدی: %s", provider, exc)
    raise last_exc or RuntimeError(f"{provider} failed")


async def _run_labeled(label: str, coro):
    try:
        return label, await coro, None
    except Exception as exc:
        return label, None, exc


async def _run_vision_ensemble(db, image_bytes: bytes, mime_type: str, amount_toman, card_number, card_holder) -> list:
    """Gemini + (در صورت تنظیم‌بودن کلید و روشن‌بودن چندمدلی) Groq/OpenRouter
    را موازی صدا می‌زند. خروجی: لیست (label, verdict) فقط برای مدل‌هایی که
    موفق شدند."""
    prompt = _PROMPT.format(
        amount=f"{amount_toman:,}" if amount_toman else "نامشخص",
        card_number=card_number or "نامشخص",
        card_holder=card_holder or "نامشخص",
    )

    tasks = [_run_labeled("Gemini", _run_gemini_vision(db, image_bytes, mime_type, amount_toman, card_number, card_holder))]

    multi_model_enabled = (await asyncio.to_thread(db.get_setting, "receipt_ai_multi_model_enabled", "1")) != "0"
    # مدل‌های بینایی Groq/OpenRouter فعلاً فقط عکس را پشتیبانی می‌کنند، نه PDF.
    if multi_model_enabled and mime_type.startswith("image/"):
        groq_keys = ai_support.resolve_groq_keys(db)
        if groq_keys:
            tasks.append(_run_labeled("Groq", _run_openai_compatible_vision(
                "groq", groq_keys, _GROQ_VISION_MODEL, prompt, image_bytes, mime_type)))
        openrouter_keys = ai_support.resolve_openrouter_keys(db)
        if openrouter_keys:
            tasks.append(_run_labeled("OpenRouter", _run_openai_compatible_vision(
                "openrouter", openrouter_keys, _OPENROUTER_VISION_MODEL, prompt, image_bytes, mime_type)))

    results = await asyncio.gather(*tasks)
    successes = []
    for label, verdict, exc in results:
        if exc is not None:
            _log.warning("receipt_ai_check: بررسی AI با %s ناموفق بود: %s", label, exc)
        else:
            successes.append((label, verdict))
    return successes


async def check_receipt(bot, db, *, file_id: str, receipt_type: str, ref_kind: str, ref_id: int,
                         amount_toman=None, card_number=None, card_holder=None, message=None) -> dict:
    """بررسی کامل یک رسید تازه‌ارسال‌شده.

    ref_kind/ref_id: نوع و شناسه‌ی رکوردی که این رسید برایش ارسال شده - مثلاً
    ("order", 123) یا ("topup", 45) - برای تشخیص رسید تکراری بین انواع مختلف.

    خروجی: {"note": str|None, "available": bool, "reject": bool, "reject_reason": str|None}
    - note: متن هشدار کوتاه فارسی برای اضافه‌شدن به پیام ادمین (None یعنی
      چیز مشکوکی پیدا نشد).
    - available: آیا حداقل یکی از سرویس‌های AI واقعاً اجرا شد یا نه. چک
      رسید تکراری (هش دقیق یا phash) همیشه مستقل از این انجام می‌شود.
    - reject: آیا این رسید آنقدر مشکوک بود که باید به‌صورت خودکار (بدون
      بررسی ادمین) رد شود.
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

    mime_type = _guess_mime(receipt_type, message)
    phash = await asyncio.to_thread(_compute_phash, image_bytes) if mime_type.startswith("image/") else None
    near_dup = await asyncio.to_thread(_find_near_duplicate, db, phash, ref_kind, ref_id)
    if near_dup:
        other_kind = "سفارش" if near_dup["ref_kind"] == "order" else "شارژ کیف پول"
        reasons.append(
            f"🟡 این رسید از نظر بصری خیلی شبیه رسیدی است که قبلاً برای {other_kind} #{near_dup['ref_id']} "
            "ارسال شده (احتمال ویرایش/فشرده‌سازی مجدد همان عکس) - چون قطعیت هش دقیق را ندارد، "
            "فقط هشدار است و رد خودکار نمی‌شود."
        )

    ela_note = await asyncio.to_thread(_ela_note, image_bytes, mime_type)
    if ela_note:
        reasons.append(ela_note)

    ai_enabled = (await asyncio.to_thread(db.get_setting, "receipt_ai_check_enabled", "1")) != "0"
    can_analyze = mime_type.startswith("image/") or mime_type == "application/pdf"

    reference_number = ""
    if ai_enabled and can_analyze:
        try:
            successes = await _run_vision_ensemble(db, image_bytes, mime_type, amount_toman, card_number, card_holder)
        except Exception as exc:
            _log.warning("receipt_ai_check: بررسی AI ناموفق بود: %s", exc)
            successes = []

        if not successes:
            available = False
        else:
            flagged = [(label, v) for label, v in successes if v.get("suspicious") and v.get("reasons")]
            for label, v in flagged:
                reasons.append(f"🤖 هشدار {label}: " + "؛ ".join(v["reasons"]))

            high_flagged = [(label, v) for label, v in flagged if v.get("confidence") == "high"]
            if high_flagged and auto_reject_enabled:
                if len(successes) == 1 or len(flagged) >= 2:
                    # فقط یک مدل کلاً در دسترس بود (رفتار قبلی)، یا حداقل دو مدل
                    # مستقل هر دو مشکوک تشخیص دادند (هم‌رایی) - رد خودکار مجاز است.
                    for label, v in high_flagged:
                        reject_reasons.append(f"🤖 هشدار {label}: " + "؛ ".join(v["reasons"]))
                else:
                    reasons.append(
                        "ℹ️ فقط یک مدل هوش مصنوعی این رسید را با اطمینان بالا مشکوک تشخیص داد ولی بقیه‌ی "
                        "مدل‌های در دسترس موردی پیدا نکردند؛ برای احتیاط رد خودکار انجام نشد و تصمیم با ادمین است."
                    )

            card_values = {v["card_number_digits"] for _, v in successes if v.get("card_number_digits")}
            if len(card_values) > 1:
                reasons.append("⚠️ مدل‌های مختلف هوش مصنوعی شماره کارت/شبای متفاوتی از متن رسید خواندند - یکی از آن‌ها ممکن است اشتباه OCR کرده باشد.")
            ref_values = {v["reference_number"] for _, v in successes if v.get("reference_number")}
            if len(ref_values) > 1:
                reasons.append("⚠️ مدل‌های مختلف هوش مصنوعی شماره پیگیری/مرجع متفاوتی از متن رسید خواندند - یکی از آن‌ها ممکن است اشتباه OCR کرده باشد.")

            chosen = next((v for label, v in successes if label == "Gemini"), successes[0][1])
            reference_number = chosen.get("reference_number") or ""
            card_number_digits = chosen.get("card_number_digits") or ""

            structural_note = _check_extracted_number(card_number_digits)
            if structural_note:
                reasons.append(structural_note)

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

    try:
        await asyncio.to_thread(db.record_receipt_hash, file_hash, ref_kind, ref_id, reference_number, phash)
    except Exception as exc:
        _log.warning("receipt_ai_check: ثبت هش/شماره مرجع رسید خطا داد: %s", exc)

    return {
        "note": "\n".join(reasons) if reasons else None,
        "available": available,
        "reject": bool(reject_reasons),
        "reject_reason": "\n".join(reject_reasons) if reject_reasons else None,
    }
