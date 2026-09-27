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
   شماره کارت/شبای مقصد، شماره پیگیری/مرجع، و مبلغ تراکنش را عیناً از متن
   رسید OCR می‌کند. روی این مقادیر خام، چک‌های کاملاً مستقل از قضاوت AI
   انجام می‌شود:
     - شماره کارت باید الگوریتم Luhn را رد کند و پیش‌شماره‌اش (۶ رقم اول)
       باید متعلق به یک بانک واقعی ایرانی باشد؛ شبا هم باید چک‌سام
       استاندارد IBAN (ISO 7064) را پاس کند. این‌ها استانداردهای واقعی
       بانکی هستند، نه حدس - یک عدد سرهم‌بندی‌شده تقریباً همیشه رد می‌شود.
     - شماره پیگیری/مرجع متن رسید در جدول receipt_hashes ذخیره و برای
       رسید تکراری چک می‌شود - مستقل از هش فایل، پس حتی اگر کاربر عکس را
       کمی ویرایش/فشرده کرده باشد (که هش فایل را عوض می‌کند) باز هم رسید
       ری‌یوزشده لو می‌رود.
     - مبلغ خام OCR شده با مبلغ مورد انتظار فاکتور به‌صورت عددی (نه با
       قضاوت مدل) مقایسه می‌شود - چون بعضی اپ‌های بانکی مبلغ را به ریال
       نشان می‌دهند، هم تومان و هم ریال (ده برابر) به‌عنوان تطابق معتبر
       پذیرفته می‌شود، با کمی تلورانس برای گرد شدن. این چک، جدا از این‌که
       خودِ مدل تصویری هم مبلغ را «قضاوت» می‌کند، یک لایه‌ی مستقل و
       دترمینیستیک اضافه می‌کند - رایج‌ترین شکل جعل (دستکاری فقط عدد مبلغ
       در یک رسید واقعی) را حتی اگر مدل تصویری اشتباه کند هم می‌گیرد.
   نکته‌ی مهم: این چک‌ها فقط زمانی اجرا می‌شوند که مقدار کاملاً خوانا و
   بدون ستاره باشد (شماره‌های ماسک‌شده اصلاً بررسی نمی‌شوند) و به‌تنهایی
   reject خودکار ایجاد نمی‌کنند (فقط note برای ادمین) - چون امکان اشتباه
   OCR روی یک رقم وجود دارد؛ فقط تکراربودن شماره مرجع/هش، به شرط
   روشن‌بودن auto-reject، خودکار رد می‌شود. استثنا: اگر مبلغ OCR شده به‌طور
   قطعی مغایرت داشته باشد و *همزمان* حداقل یک مدل تصویری هم آن رسید را با
   اطمینان «high» مشکوک تشخیص داده باشد (حتی وقتی فقط همان یک مدل موجود
   بوده)، این دو منبع مستقل (OCR عددی + قضاوت مدل) هم‌رای در نظر گرفته
   می‌شوند و طبق همان قاعده‌ی «حداقل دو منبع مستقل» در بخش (۴) رد خودکار
   انجام می‌شود.

۶) تحلیل فرنزیک تصویر (ELA - Error Level Analysis): فقط برای فایل‌های
   JPEG، تصویر با کیفیت ثابت (۹۰) دوباره فشرده و با نسخه‌ی اصلی مقایسه
   می‌شود. اگر یک ناحیه‌ی محدود از عکس نرخ خطای فشرده‌سازی خیلی متفاوتی
   نسبت به بقیه‌ی تصویر داشته باشد، نشانه‌ی احتمالی ویرایش/جای‌گذاری موضعی
   (مثلاً دستکاری روی عدد مبلغ) است - این یک چک کاملاً بدون AI و
   دترمینیستیک است، ولی چون ممکن است هشدار اشتباه هم بدهد (فشرده‌سازی
   چندباره‌ی خودِ تلگرام)، همیشه فقط «note» است، هرگز باعث رد خودکار
   نمی‌شود.

۷) سه چک اضافی برای رسیدهایی که مبلغ/شماره کارتشان کاملاً درست است ولی از
   یک منبع دیگر لو می‌روند (رایج در جعل «حرفه‌ای‌تر» - مثلاً رسید واقعیِ
   قدیمیِ خودِ کاربر که دوباره برای این خرید فرستاده شده، بدون دستکاری
   هیچ رقمی):
     - ساعت نوار وضعیت گوشی در اسکرین‌شات (status_bar_time، اگر خوانا
       باشد) با ساعت واقعی ارسال پیام به ربات (به وقت تهران) مقایسه
       می‌شود. اگر فاصله‌ی این دو زیاد باشد (مثلاً چند ساعت)، یعنی
       اسکرین‌شات مدتی قبل از ارسال گرفته شده - می‌تواند یک رسید قدیمی
       (واقعی یا حتی برای تراکنش دیگری) باشد که همین حالا دوباره فرستاده
       شده. چون تاخیر طبیعی بین گرفتن اسکرین‌شات و ارسالش هم وجود دارد
       (بازکردن گالری، تردید کاربر و...)، تلورانس این چک نسبتاً بزرگ در
       نظر گرفته شده - فقط note، هرگز reject خودکار.
     - پیش‌شماره‌ی (۶ رقم اول) کارت مبدأ/پرداخت‌کننده که داخل متن رسید
       چاپ شده، با نامِ بانک/برندی که مدل از روی ظاهر تصویر (لوگو، رنگ،
       اسم اپ در بالای صفحه) تشخیص می‌دهد مقایسه می‌شود - این دو باید به
       یک بانک اشاره کنند. اگر رسید واقعاً مال یک اپ بانکی خاص باشد ولی
       شماره کارت مبدأ داخل متن به بانک دیگری تعلق داشته باشد (مثلاً
       عکس/قالب یک اپ با شماره کارت جعلی/دستکاری‌شده ترکیب شده)، ناسازگاری
       آشکار می‌شود. چون تشخیص بصری برند اپ توسط مدل خودش هم می‌تواند
       گاهی اشتباه باشد، این هم فقط note است.
     - نام فایل رسید ارسالی (فقط وقتی به‌صورت «فایل/سند» تلگرام - نه
       عکس فشرده‌ی معمولی - فرستاده شده باشد، چون تلگرام نام فایل اصلی
       عکس‌های معمولی را حذف می‌کند): اگر با الگوی استاندارد اسکرین‌شات
       اندروید/فوروارد واتس‌اپ (که خودش تاریخ/ساعت گرفتن عکس را در نام
       فایل دارد) مطابقت داشته باشد ولی آن تاریخ با زمان واقعی ارسال به
       ربات خیلی فاصله داشته باشد (رسید/اسکرین‌شات قدیمی)، یا اگر نام
       فایل حاوی نام ابزارهای ویرایش عکس شناخته‌شده باشد، به‌عنوان یک
       نشانه‌ی ضعیف گزارش می‌شود - فقط note، چون کاربر می‌تواند عمداً یا
       سهواً نام فایل را عوض کرده باشد.
"""

import asyncio
import base64
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:
    _TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

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

علاوه بر این چند مقدار خام را هم دقیقاً همان‌طور که در عکس نوشته شده (بدون
فاصله، بدون خط‌تیره، بدون کلمه‌ی «ریال»/«تومان»، فقط رقم/حروف انگلیسی)
استخراج کن - این فیلدها صرفاً OCR/مشاهده‌ی خام هستند، قضاوتی درباره‌شان نکن:
- شماره کارت یا شبای مقصد که داخل خودِ متن رسید چاپ شده (همانی که رسید ادعا
  می‌کند پول به آن واریز شده)، اگر بخشی از آن با ستاره پوشانده شده رقم‌های
  ستاره‌دار را هم به همان شکل با کاراکتر * بگذار.
- شماره کارت مبدأ/پرداخت‌کننده (کارتی که پول از آن کم شده)، به همان شکل
  که در متن رسید چاپ شده، رقم‌های ستاره‌دار را هم با * نگه دار.
- شماره پیگیری/مرجع/سند تراکنش (هرکدام که در رسید هست).
- مبلغ تراکنش، فقط رقم خام (مثلاً برای «۱۵۰,۰۰۰ تومان» بنویس 150000)، دقیقاً
  همان عددی که در رسید چاپ شده - توجه کن اپ‌های بانکی ایرانی گاهی مبلغ را به
  ریال نشان می‌دهند (ده برابر تومان)، فقط همان رقم خام را بدون تبدیل واحد
  بنویس.
- اگر رسید اسکرین‌شات یک گوشی موبایل است و نوار وضعیت (status bar) بالای
  صفحه ساعت گوشی را نشان می‌دهد، همان ساعت را با فرمت ۲۴ ساعته HH:MM
  بنویس (مثلاً 14:32). اگر رسید اسکرین‌شات موبایل نیست یا نوار وضعیت
  ساعت ندارد/ناخوانا است، رشته خالی بگذار.
- صرفاً بر اساس ۶ رقم اول شماره کارت مبدأ که در بالا نوشتی (نه ظاهر
  تصویر)، با دانش عمومی خودت از پیش‌شماره‌های بانک‌های ایرانی حدس بزن این
  کارت متعلق به کدام بانک است؛ فقط اسم بانک را به فارسی بنویس (مثلاً
  «بانک ملت»). اگر شماره کارت مبدأ ناخوانا/ستاره‌دار بود یا مطمئن نیستی،
  رشته خالی بگذار.
- کاملاً مستقل از فیلد قبلی و صرفاً بر اساس ظاهر تصویر (لوگو، رنگ اپ،
  اسم برند نوشته‌شده در بالای صفحه یا هدر رسید)، حدس بزن این اسکرین‌شات/
  رسید مربوط به اپلیکیشن یا فیش کدام بانک ایرانی است؛ فقط اسم بانک را به
  فارسی بنویس. اگر برندینگ اپ در تصویر مشخص نیست (مثلاً رسید کاغذی خام
  بدون لوگو)، رشته خالی بگذار.
اگر هرکدام خوانده نشد یا وجود نداشت، رشته خالی "" بگذار.

فقط یک JSON خام و بدون هیچ توضیح اضافه یا Markdown، دقیقاً با این فرمت برگردان:
{{"suspicious": true/false, "confidence": "low"/"high", "reasons": ["دلیل کوتاه فارسی", ...], "card_number_digits": "...", "source_card_digits": "...", "reference_number": "...", "amount_digits": "...", "status_bar_time": "...", "bin_bank_name": "...", "app_bank_name": "..."}}

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
اگر چیز غیرعادی ندیدی: {{"suspicious": false, "confidence": "low", "reasons": [], "card_number_digits": "...", "source_card_digits": "...", "reference_number": "...", "amount_digits": "...", "status_bar_time": "...", "bin_bank_name": "...", "app_bank_name": "..."}}"""


_FORENSIC_PROMPT = """این یک بررسی تخصصی فورنزیک برای تشخیص رسید بانکی جعلی است.
فرض نکن که عبارت «عملیات موفق» یا ظاهر کلی تصویر به معنی واقعی بودن تراکنش است.
تو فقط اصالت بصری/دیجیتال خودِ تصویر را ارزیابی می‌کنی؛ قرار نیست وجود واقعی تراکنش بانکی را تأیید کنی.

تصویر را با دقت پیکسل‌به‌پیکسل و از چند زاویه بررسی کن:
1) آیا تصویر بیشتر شبیه یک اسکرین‌شات طبیعی از یک اپ واقعی است یا یک تصویر بازسازی‌شده/ساخته‌شده؟
2) هم‌ترازی متن‌ها، فاصله خطوط، baseline فونت، ضخامت حروف، anti-aliasing، رنگ، سایه، لبه‌ها و اندازه‌ی عناصر را بررسی کن.
3) نواحی عددی حساس مثل مبلغ، شماره کارت، تاریخ، ساعت و شماره پیگیری را با بقیه‌ی UI مقایسه کن؛ دنبال فونت/رزولوشن/فشرده‌سازی متفاوت، halo، برش، paste، blur موضعی یا تغییر کیفیت باش.
4) ساختار کلی UI، هدر، لوگو، دکمه‌ها، نوار وضعیت و نسبت‌های فضایی را بررسی کن. اگر چیزی با یک اسکرین‌شات طبیعی از همان نوع اپ ناسازگار است، مشخص کن.
5) تناقض‌های داخلی تصویر را پیدا کن؛ مثلاً متن یا بانک اعلام‌شده با کارت/برندینگ/ساختار رسید همخوان نباشد.
6) نشانه‌های تولید مصنوعی، بازسازی با ویرایشگر، compositing، screenshot-of-screenshot یا تغییر موضعی را بررسی کن.
7) اگر شواهد کافی نداری، امتیاز بالا نده و چیزی را حدس نزن. کیفیت پایین یا فشرده‌سازی معمولی به‌تنهایی جعل نیست.

این بخش را به خروجی JSON اصلی بررسی رسید اضافه کن و یک JSON واحد برگردان؛
فیلدهای فورنزیک عبارت‌اند از:
"forensic_score": 0, "forensic_confidence": "low", "synthetic": false,
"tamper": false, "indicators": ["..."], "strong_indicators": ["..."]

مقیاس forensic_score:
0-19 = تقریباً بدون نشانه
20-44 = ضعیف/مبهم
45-69 = مشکوک
70-84 = بسیار مشکوک
85-100 = شواهد بصری قوی برای جعل/بازسازی

forensic_confidence فقط low/medium/high باشد. فقط وقتی high بگذار که حداقل دو نشانه‌ی مستقل و مشخص در خود تصویر دیده شود.
"""


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


_AMOUNT_TOLERANCE_RATIO = 0.02  # ۲٪ - برای گرد شدن‌های جزئی نمایش بعضی اپ‌های بانکی
_AMOUNT_TOLERANCE_MIN = 500  # حداقل تلورانس مطلق (تومان) برای مبالغ خیلی کوچک


def _check_amount_mismatch(amount_digits: str, expected_amount_toman) -> "str | None":
    """مبلغ خامی که مدل تصویری از متن رسید OCR کرده را با مبلغ مورد انتظار
    فاکتور به‌صورت قطعی (نه با قضاوت AI) مقایسه می‌کند. چون اپ‌های بانکی
    ایرانی گاهی مبلغ را به ریال نشان می‌دهند (ده برابر تومان)، هر دو حالت
    ریال/تومان به‌عنوان تطبیق معتبر پذیرفته می‌شود. این چک فقط زمانی اجرا
    می‌شود که رقم کاملاً خوانا باشد؛ مثل بقیه‌ی چک‌های قطعی این ماژول، شکستش
    هرگز به‌تنهایی باعث رد خودکار نمی‌شود - فقط یک نشانه‌ی قوی برای ادمین/رد
    خودکار در کنار حداقل یک تشخیص مستقل دیگر است."""
    if not amount_digits or not amount_digits.isdigit() or not expected_amount_toman:
        return None
    try:
        seen = int(amount_digits)
        expected = int(expected_amount_toman)
    except (ValueError, TypeError):
        return None
    if seen <= 0 or expected <= 0:
        return None
    for candidate in (expected, expected * 10):
        tolerance = max(candidate * _AMOUNT_TOLERANCE_RATIO, _AMOUNT_TOLERANCE_MIN)
        if abs(seen - candidate) <= tolerance:
            return None
    return (
        f"⚠️ مبلغی که از متن رسید خوانده شد ({seen:,}) با مبلغ مورد انتظار فاکتور "
        f"({expected:,} تومان) مطابقت ندارد (نه به‌صورت تومان، نه ریال) - این یک "
        "چک عددی مستقل از قضاوت هوش مصنوعی است."
    )


_STATUS_BAR_TOLERANCE_MINUTES = 90  # تلورانس بزرگ عمدی - فقط note است، هدف گرفتن فاصله‌ی چند ساعته/چندروزه است


def _check_status_bar_time(status_bar_time: str, message) -> "str | None":
    """ساعت نوار وضعیت گوشی در اسکرین‌شات را با ساعت واقعی ارسال پیام به ربات
    (به وقت تهران) مقایسه می‌کند. اگر فاصله زیاد باشد یعنی این اسکرین‌شات
    مدتی قبل از ارسال گرفته شده - نشانه‌ی احتمالی رسید قدیمی که دوباره
    فرستاده شده، حتی اگر خودِ عکس با هیچ رسید قبلی در دیتابیس یکی/شبیه
    نباشد (مثلاً یک رسید واقعی و متفاوت که کاربر مدت‌ها نگه داشته بود)."""
    if not status_bar_time or not re.fullmatch(r"\d{1,2}:\d{2}", status_bar_time):
        return None
    send_dt = getattr(message, "date", None) if message is not None else None
    if send_dt is None:
        return None
    try:
        if send_dt.tzinfo is None:
            send_dt = send_dt.replace(tzinfo=timezone.utc)
        send_local = send_dt.astimezone(_TEHRAN_TZ)
        hh, mm = status_bar_time.split(":")
        hh, mm = int(hh), int(mm)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        shot_minutes = hh * 60 + mm
        send_minutes = send_local.hour * 60 + send_local.minute
        diff = abs(shot_minutes - send_minutes)
        diff = min(diff, 1440 - diff)  # دور زدن نیمه‌شب
        if diff > _STATUS_BAR_TOLERANCE_MINUTES:
            return (
                f"⏰ ساعت نوار وضعیت گوشی در اسکرین‌شات ({status_bar_time}) با ساعت واقعی ارسال "
                f"همین رسید به ربات ({send_local.strftime('%H:%M')} به وقت تهران) حدود {diff} دقیقه "
                "فاصله دارد - ممکن است این اسکرین‌شات مدتی قبل گرفته شده و رسید قدیمی/بازارسالی باشد."
            )
    except Exception as exc:
        _log.warning("receipt_ai_check: مقایسه‌ی ساعت نوار وضعیت خطا داد: %s", exc)
    return None


def _normalize_bank_name(name: str) -> str:
    name = (name or "").strip().lower()
    for junk in ("بانک", "bank", "‌", " ", "-", "_"):
        name = name.replace(junk, "")
    return name


def _check_bank_name_mismatch(bin_bank_name: str, app_bank_name: str) -> "str | None":
    """نام بانکی که مدل صرفاً از روی ۶ رقم اول کارت مبدأ حدس زده را با نام
    بانکی که مدل مستقلاً از روی ظاهر/برندینگ تصویر تشخیص داده مقایسه
    می‌کند. این دو باید یک بانک را نشان بدهند؛ اگر آشکارا متفاوت باشند
    (نه فقط اختلاف املایی جزئی)، یعنی یا شماره کارت مبدأ با قالب/برند
    واقعی رسید همخوانی ندارد (نشانه‌ی ترکیب قالب یک اپ با شماره کارت
    دستکاری‌شده) یا خودِ مدل در یکی از دو حدس اشتباه کرده - در هر دو حالت
    فقط یک note برای بررسی بیشتر ادمین است، نه رد خودکار."""
    a, b = _normalize_bank_name(bin_bank_name), _normalize_bank_name(app_bank_name)
    if not a or not b:
        return None
    if a in b or b in a:
        return None
    return (
        f"⚠️ بر اساس پیش‌شماره‌ی کارت مبدأ، بانک صادرکننده باید «{bin_bank_name}» باشد، ولی ظاهر/برندینگ "
        f"اپلیکیشن در تصویر رسید به «{app_bank_name}» شبیه‌تر است - این دو باید یکی باشند."
    )


_SCREENSHOT_FILENAME_PATTERNS = (
    # اسکرین‌شات اندروید: Screenshot_20260315-143207.jpg یا Screenshot_2026-03-15-14-32-07.png
    re.compile(r"Screenshot_(\d{4})-?(\d{2})-?(\d{2})[-_](\d{2})-?(\d{2})-?(\d{2})", re.IGNORECASE),
    # فوروارد واتس‌اپ: IMG-20260315-WA0001.jpg (ساعت ندارد، فقط تاریخ)
    re.compile(r"IMG-(\d{4})(\d{2})(\d{2})-WA\d+", re.IGNORECASE),
)

_SUSPICIOUS_FILENAME_KEYWORDS = (
    "photoshop", "ps_edit", "picsart", "snapseed", "lightroom", "remini",
    "editor", "edited", "fake", "canva", "photopea", "inpaint", "retouch",
)

_FILENAME_DATE_TOLERANCE = timedelta(days=2)


def _check_receipt_filename(receipt_type: str, message) -> "str | None":
    """نام فایل رسید ارسالی را بررسی می‌کند - فقط وقتی به‌صورت «فایل/سند»
    تلگرام (نه عکس فشرده‌ی معمولی) فرستاده شده باشد، چون تلگرام نام فایل
    اصلی عکس‌های معمولی را حذف می‌کند و آن‌ها را با نامی تصادفی جایگزین
    می‌کند. دو چیز را چک می‌کند: تاریخ/ساعت جاسازشده در نام‌های استاندارد
    اسکرین‌شات اندروید/فوروارد واتس‌اپ (اگر با زمان واقعی ارسال خیلی
    فاصله داشته باشد یعنی اسکرین‌شات قدیمی است) و کلیدواژه‌ی ابزارهای
    ویرایش عکس در نام فایل. هر دو فقط note هستند - کاربر می‌تواند نام فایل
    را عمداً یا سهواً عوض کرده باشد، پس قطعیت این چک از هش/OCR کمتر است."""
    if receipt_type != "document" or message is None:
        return None
    doc = getattr(message, "document", None)
    file_name = getattr(doc, "file_name", None) if doc else None
    if not file_name:
        return None

    lowered = file_name.lower()
    for kw in _SUSPICIOUS_FILENAME_KEYWORDS:
        if kw in lowered:
            return (
                f"🗂 نام فایل رسید ارسالی («{file_name}») حاوی نام یک ابزار/اپ ویرایش عکس شناخته‌شده "
                "است - ممکن است تصویر پیش از ارسال ویرایش شده باشد."
            )

    send_dt = getattr(message, "date", None)
    if send_dt is None:
        return None
    if send_dt.tzinfo is None:
        send_dt = send_dt.replace(tzinfo=timezone.utc)

    for pattern in _SCREENSHOT_FILENAME_PATTERNS:
        m = pattern.search(file_name)
        if not m:
            continue
        groups = m.groups()
        try:
            if len(groups) == 6:
                y, mo, d, hh, mi, ss = (int(g) for g in groups)
                shot_dt = datetime(y, mo, d, hh, mi, ss, tzinfo=_TEHRAN_TZ)
            else:
                y, mo, d = (int(g) for g in groups)
                shot_dt = datetime(y, mo, d, tzinfo=_TEHRAN_TZ)
        except ValueError:
            continue
        send_local = send_dt.astimezone(_TEHRAN_TZ)
        if abs((send_local - shot_dt)) > _FILENAME_DATE_TOLERANCE:
            return (
                f"🗂 بر اساس نام فایل ارسالی («{file_name}»)، این اسکرین‌شات در تاریخ "
                f"{shot_dt.strftime('%Y-%m-%d %H:%M')} گرفته شده - در حالی که همین حالا "
                f"({send_local.strftime('%Y-%m-%d %H:%M')}) ارسال شده؛ ممکن است اسکرین‌شات/رسید "
                "قدیمی دوباره فرستاده شده باشد."
            )
        break
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


# وزن‌های محلی فورنزیک: این امتیاز «احتمال دستکاری» است، نه اثبات جعل.
# هدف این است که ELA ضعیف قبلی به یک مجموعه چک مستقل تبدیل شود.
def _local_forensic_scan(image_bytes: bytes, mime_type: str) -> dict:
    result = {"score": 0, "indicators": [], "strong": []}
    if not mime_type.startswith("image/"):
        return result
    try:
        from PIL import Image, ImageChops, ImageStat, ImageFilter
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if w < 300 or h < 500:
            return result

        # 1) چند سطح ELA: جعل موضعی معمولاً در یک کیفیت بازفشرده‌سازی، فقط یک ناحیه را جدا می‌کند.
        if mime_type == "image/jpeg":
            gray = img.convert("L")
            local_scores = []
            for quality in (75, 85, 92):
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=quality, optimize=False)
                buf.seek(0)
                resaved = Image.open(buf).convert("RGB")
                diff = ImageChops.difference(img, resaved)
                stat = ImageStat.Stat(diff)
                overall = sum(stat.mean) / 3.0
                if overall <= 0.05:
                    continue
                grid = 12
                bw, bh = max(w // grid, 1), max(h // grid, 1)
                vals = []
                for gy in range(grid):
                    for gx in range(grid):
                        box = (gx*bw, gy*bh, min((gx+1)*bw,w), min((gy+1)*bh,h))
                        if box[2] <= box[0] or box[3] <= box[1]:
                            continue
                        vals.append(sum(ImageStat.Stat(diff.crop(box)).mean)/3.0)
                if vals:
                    vals_sorted = sorted(vals)
                    median = vals_sorted[len(vals_sorted)//2]
                    p90 = vals_sorted[max(0, int(len(vals_sorted)*0.90)-1)]
                    mx = max(vals)
                    if median > 0 and mx > median * 6 and p90 > median * 2.5:
                        local_scores.append(1)
            if local_scores:
                result["score"] += min(25, 10 * len(local_scores))
                result["indicators"].append("ناهمگونی موضعی فشرده‌سازی در چند سطح ELA دیده شد")
                if len(local_scores) >= 2:
                    result["strong"].append("ناهمگونی موضعی در چند سطح بازفشرده‌سازی تکرار شد")

        # 2) نواحی متن/عدد: اختلاف شدید شارپنس موضعی می‌تواند نشانه paste/retouch باشد.
        # این چک فقط وقتی تفاوت از چند ناحیه عبور کند امتیاز می‌دهد تا خطوط طبیعی UI کافی نباشند.
        small = img.resize((max(64, w//8), max(64, h//8)), Image.LANCZOS)
        edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
        est = ImageStat.Stat(edges)
        mean_edge = sum(est.mean) / len(est.mean)
        if mean_edge > 18:
            # high-frequency map on a coarse grid
            pix = edges.load(); sw, sh = small.size
            vals=[]
            for gy in range(8):
                for gx in range(8):
                    x0,x1=int(gx*sw/8),int((gx+1)*sw/8)
                    y0,y1=int(gy*sh/8),int((gy+1)*sh/8)
                    crop=edges.crop((x0,y0,x1,y1))
                    vals.append(sum(ImageStat.Stat(crop).mean)/3.0)
            vals.sort()
            med=vals[len(vals)//2]
            hi=sum(1 for v in vals if med>0 and v>med*2.2)
            if hi >= 3:
                result["score"] += 8
                result["indicators"].append("چند ناحیه از تصویر شارپنس/ریزجزئیات متفاوتی با بدنه اصلی دارند")

        # 3) نسبت تصویر رایج برای اسکرین‌شات عمودی: به‌تنهایی نشانه جعل نیست، فقط context است.
        ratio = w / float(h)
        if 0.43 <= ratio <= 0.55 and h >= 1200:
            result["indicators"].append("تصویر از نظر ابعاد با اسکرین‌شات عمودی موبایل سازگار است")

        result["score"] = min(40, result["score"])
        return result
    except Exception as exc:
        _log.warning("receipt_ai_check: local forensic scan failed: %s", exc)
        return result


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
        forensic_confidence = str(data.get("forensic_confidence") or "low").strip().lower()
        if forensic_confidence not in ("low", "medium", "high"):
            forensic_confidence = "low"
        try:
            forensic_score = max(0, min(100, int(float(data.get("forensic_score") or 0))))
        except (TypeError, ValueError):
            forensic_score = 0
        return {
            "suspicious": bool(data.get("suspicious")),
            "confidence": confidence,
            "reasons": [str(r).strip() for r in (data.get("reasons") or []) if str(r).strip()],
            "card_number_digits": str(data.get("card_number_digits") or "").strip(),
            "source_card_digits": str(data.get("source_card_digits") or "").strip(),
            "reference_number": str(data.get("reference_number") or "").strip(),
            "amount_digits": str(data.get("amount_digits") or "").strip(),
            "status_bar_time": str(data.get("status_bar_time") or "").strip(),
            "bin_bank_name": str(data.get("bin_bank_name") or "").strip(),
            "app_bank_name": str(data.get("app_bank_name") or "").strip(),
            "forensic_score": forensic_score,
            "forensic_confidence": forensic_confidence,
            "synthetic": bool(data.get("synthetic")),
            "tamper": bool(data.get("tamper")),
            "indicators": [str(r).strip() for r in (data.get("indicators") or []) if str(r).strip()],
            "strong_indicators": [str(r).strip() for r in (data.get("strong_indicators") or []) if str(r).strip()],
        }
    except Exception:
        return {
            "suspicious": False, "confidence": "low", "reasons": [],
            "card_number_digits": "", "source_card_digits": "", "reference_number": "",
            "amount_digits": "", "status_bar_time": "", "bin_bank_name": "", "app_bank_name": "",
            "forensic_score": 0, "forensic_confidence": "low", "synthetic": False, "tamper": False,
            "indicators": [], "strong_indicators": [],
        }


async def _run_gemini_vision(db, image_bytes: bytes, mime_type: str, amount_toman, card_number, card_holder, prompt_override: str | None = None) -> dict:
    """تحلیل تصویری با Gemini - کلیدها/rotate دقیقاً همان چیزی است که
    ai_support._run_gemini استفاده می‌کند تا تنظیمات پنل ادمین یکسان برای
    هر دو کاربرد به‌کار برود."""
    from google.genai import types

    api_keys = ai_support.resolve_gemini_keys(db)
    if not api_keys:
        raise RuntimeError("gemini_api_key تنظیم نشده")

    model_name = ai_support.resolve_gemini_model(db)
    prompt = prompt_override or _PROMPT.format(
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
    ) + "\n\n" + _FORENSIC_PROMPT + "\n\nمهم: فقط یک JSON نهایی برگردان و همه فیلدهای استخراجی قبلی + فیلدهای فورنزیک را در همان JSON قرار بده."

    tasks = [_run_labeled("Gemini", _run_gemini_vision(db, image_bytes, mime_type, amount_toman, card_number, card_holder, prompt_override=prompt))]

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

    local_forensics = await asyncio.to_thread(_local_forensic_scan, image_bytes, mime_type)
    local_forensic_score = int(local_forensics.get("score") or 0)
    for ind in local_forensics.get("indicators") or []:
        reasons.append("🔬 فورنزیک محلی: " + ind)

    filename_note = _check_receipt_filename(receipt_type, message)
    if filename_note:
        reasons.append(filename_note)

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

            # امتیاز فورنزیک از همه‌ی مدل‌ها؛ این با suspicious فرق دارد و مدل را مجبور می‌کند
            # به‌جای یک «بله/خیر» مبهم، شواهد تصویری را وزن‌دهی کند.
            forensic_models = [(label, v) for label, v in successes if int(v.get("forensic_score") or 0) > 0]
            if forensic_models:
                best_forensic = max(int(v.get("forensic_score") or 0) for _, v in forensic_models)
                high_forensic_votes = [
                    (label, v) for label, v in forensic_models
                    if int(v.get("forensic_score") or 0) >= 80 and v.get("forensic_confidence") == "high"
                ]
                if best_forensic >= 45:
                    labels = "، ".join(f"{label}: {int(v.get('forensic_score') or 0)}/100" for label, v in forensic_models)
                    reasons.append(f"🧠 امتیاز فورنزیک تصویری: {labels}")
                for label, v in forensic_models:
                    for ind in v.get("indicators") or []:
                        reasons.append(f"🔎 فورنزیک {label}: {ind}")
            else:
                best_forensic = 0
                high_forensic_votes = []

            chosen = next((v for label, v in successes if label == "Gemini"), successes[0][1])
            amount_digits = chosen.get("amount_digits") or ""
            amount_note = _check_amount_mismatch(amount_digits, amount_toman)
            amount_mismatch = amount_note is not None

            status_bar_note = _check_status_bar_time(chosen.get("status_bar_time") or "", message)
            if status_bar_note:
                reasons.append(status_bar_note)

            bank_mismatch_note = _check_bank_name_mismatch(
                chosen.get("bin_bank_name") or "", chosen.get("app_bank_name") or "",
            )
            if bank_mismatch_note:
                reasons.append(bank_mismatch_note)

            high_flagged = [(label, v) for label, v in flagged if v.get("confidence") == "high"]
            # رد خودکار فقط وقتی فعال است که یک سیگنال قوی، حداقل یک شاهد مستقل دیگر داشته باشد.
            # برای جعل تصویری حرفه‌ای، فورنزیک AI می‌تواند شاهد دوم باشد؛ اما صرف score متوسط هرگز کافی نیست.
            if auto_reject_enabled:
                independent_visual = (
                    len(high_flagged) >= 2
                    or len(high_forensic_votes) >= 2
                    or (high_flagged and local_forensic_score >= 18)
                    or (high_forensic_votes and local_forensic_score >= 12)
                )
                independent_numeric = amount_mismatch and bool(high_flagged or high_forensic_votes)
                if independent_visual or independent_numeric:
                    for label, v in high_flagged:
                        reject_reasons.append(f"🤖 هشدار {label}: " + "؛ ".join(v.get("reasons") or ["نشانه‌ی قوی جعل تصویری"]))
                    for label, v in high_forensic_votes:
                        strong = v.get("strong_indicators") or v.get("indicators") or ["نشانه‌های فورنزیک قوی"]
                        reject_reasons.append(f"🧠 فورنزیک {label} ({int(v.get('forensic_score') or 0)}/100): " + "؛ ".join(strong))
                    if local_forensic_score >= 18:
                        reject_reasons.append("🔬 فورنزیک محلی نیز نشانه‌ی مستقل دستکاری/بازسازی تصویر پیدا کرد")
                    if amount_mismatch and amount_note:
                        reject_reasons.append(amount_note)
                elif high_flagged or high_forensic_votes:
                    reasons.append(
                        "ℹ️ رسید نشانه‌ی قوی از یک منبع هوش مصنوعی دارد، اما برای جلوگیری از رد اشتباه، "
                        "شاهد مستقل کافی برای رد خودکار وجود نداشت؛ بررسی انسانی توصیه می‌شود."
                    )

            card_values = {v["card_number_digits"] for _, v in successes if v.get("card_number_digits")}
            if len(card_values) > 1:
                reasons.append("⚠️ مدل‌های مختلف هوش مصنوعی شماره کارت/شبای متفاوتی از متن رسید خواندند - یکی از آن‌ها ممکن است اشتباه OCR کرده باشد.")
            ref_values = {v["reference_number"] for _, v in successes if v.get("reference_number")}
            if len(ref_values) > 1:
                reasons.append("⚠️ مدل‌های مختلف هوش مصنوعی شماره پیگیری/مرجع متفاوتی از متن رسید خواندند - یکی از آن‌ها ممکن است اشتباه OCR کرده باشد.")
            amount_values = {v["amount_digits"] for _, v in successes if v.get("amount_digits")}
            if len(amount_values) > 1:
                reasons.append("⚠️ مدل‌های مختلف هوش مصنوعی مبلغ متفاوتی از متن رسید خواندند - یکی از آن‌ها ممکن است اشتباه OCR کرده باشد.")

            reference_number = chosen.get("reference_number") or ""
            card_number_digits = chosen.get("card_number_digits") or ""

            structural_note = _check_extracted_number(card_number_digits)
            if structural_note:
                reasons.append(structural_note)
            source_card_digits = chosen.get("source_card_digits") or ""
            source_structural_note = _check_extracted_number(source_card_digits)
            if source_structural_note:
                reasons.append("⚠️ کارت مبدأ: " + source_structural_note.replace("⚠️ ", ""))

            if amount_note and amount_note not in reasons:
                reasons.append(amount_note)

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
