# -*- coding: utf-8 -*-
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
"""ساخت پست و کمپین تبلیغاتی کانال با AI داخل پنل مدیریت بات (منوی «ابزار دیپ‌لینک و پست کانال»)."""

import asyncio
import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import campaign_ai
import channel_ai
from i18n import tr
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
from states import AdminCampaign, AdminChannelAI

_log = logging.getLogger("admin_campaign")
_BACK = "adm_deeplink_tools"
_CHANNEL_SETTING = "promo_channel_id"
_CHANNEL_RE = re.compile(r"^(-100\d{5,}|@[A-Za-z][A-Za-z0-9_]{3,})$")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(text), callback_data=data) for text, data in row] for row in rows
    ])


def _cancel_kb() -> InlineKeyboardMarkup:
    return _kb([("❌ لغو", "adm_camp_cancel")])


def _variant_text(index: int, v: dict) -> str:
    param = campaign_ai.start_param_for(v["deeplink"]) or "بدون دیپ‌لینک"
    text = f"<b>━━ نسخه {index}: {html.escape(v['angle'])} ━━</b>\n\n{html.escape(v['caption'])}\n\n"
    text += f"🔘 دکمه: {html.escape(v['button_text'])}\n🔗 دیپ‌لینک: <code>{html.escape(param)}</code>"
    if v["note_for_admin"]:
        text += f"\n💡 {html.escape(v['note_for_admin'])}"
    return text


def register(router: Router, db, senior_admin_only, deny_mid):

    async def _post_markup(bot: Bot, data: dict) -> InlineKeyboardMarkup:
        me = await bot.get_me()
        param = campaign_ai.start_param_for(data["variant"]["deeplink"])
        url = f"https://t.me/{me.username}?start={param}" if param else f"https://t.me/{me.username}"
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=data["variant"]["button_text"], url=url)]])

    async def _send_post(bot: Bot, chat_id, data: dict):
        caption = html.escape(data["variant"]["caption"])
        markup = await _post_markup(bot, data)
        if data.get("photo_id"):
            await bot.send_photo(chat_id=chat_id, photo=data["photo_id"], caption=caption, reply_markup=markup)
        else:
            await bot.send_message(chat_id=chat_id, text=caption, reply_markup=markup)

    async def _generate_and_show(target: Message, state: FSMContext, goal: str):
        status = await target.answer("⏳ در حال تولید نسخه‌ها با AI از روی محصولات و کدهای تخفیف واقعی...")
        try:
            variants, _facts = await campaign_ai.generate_campaigns(db, goal)
        except Exception as exc:
            _log.warning("تولید کمپین ناموفق بود: %s", exc)
            await status.edit_text(
                "❌ تولید با AI انجام نشد: " + html.escape(str(exc)),
                reply_markup=_kb([("🔄 تلاش دوباره", "adm_camp_regen")], [("⬅️ بازگشت", _BACK)]),
            )
            await state.update_data(goal=goal)
            await state.set_state(AdminCampaign.choosing)
            return
        await state.update_data(goal=goal, variants=variants)
        await state.set_state(AdminCampaign.choosing)
        try:
            await status.delete()
        except Exception:
            pass
        for i, v in enumerate(variants, 1):
            await target.answer(_variant_text(i, v))
        pick_row = [(f"✅ نسخه {i}", f"adm_camp_pick:{i - 1}") for i in range(1, len(variants) + 1)]
        await target.answer(
            "کدام نسخه منتشر شود؟",
            reply_markup=_kb(pick_row, [("🔄 تولید دوباره", "adm_camp_regen"), ("✏️ تغییر هدف", "adm_camp_goal")], [("❌ لغو", "adm_camp_cancel")]),
        )

    async def _ask_goal(call_or_msg, state: FSMContext):
        await state.set_state(AdminCampaign.waiting_goal)
        text = ("🤖 هدف کمپین را بنویس (مثلاً «فروش ویژه آخر هفته» یا «معرفی کانفیگ تست»).\n"
                "AI فقط از محصولات، قیمت‌ها و کدهای تخفیف واقعی فروشگاه استفاده می‌کند.")
        markup = _kb([("▶️ بدون هدف خاص", "adm_camp_nogoal")], [("❌ لغو", "adm_camp_cancel")])
        if isinstance(call_or_msg, CallbackQuery):
            await call_or_msg.message.answer(text, reply_markup=markup)
            await call_or_msg.answer()
        else:
            await call_or_msg.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "adm_camp_start")
    async def cb_start(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        if not channel_ai.text_configured(db):
            await call.answer("مدل متن کانال تنظیم نشده؛ از «مدل‌های AI کانال» کلید Jarvis را وارد کن.", show_alert=True)
            return
        await state.clear()
        await _ask_goal(call, state)

    @router.callback_query(F.data == "adm_camp_goal")
    async def cb_goal(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await _ask_goal(call, state)

    @router.callback_query(F.data == "adm_camp_nogoal")
    async def cb_nogoal(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await call.answer()
        await _generate_and_show(call.message, state, "")

    @router.message(AdminCampaign.waiting_goal, F.text)
    async def msg_goal(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            await state.clear()
            return
        await _generate_and_show(message, state, (message.text or "").strip())

    @router.callback_query(F.data == "adm_camp_regen")
    async def cb_regen(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        data = await state.get_data()
        await call.answer()
        await _generate_and_show(call.message, state, data.get("goal", ""))

    @router.callback_query(F.data.startswith("adm_camp_pick:"))
    async def cb_pick(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        data = await state.get_data()
        variants = data.get("variants") or []
        try:
            variant = variants[int(call.data.split(":", 1)[1])]
        except (ValueError, IndexError):
            await call.answer("این نسخه دیگر معتبر نیست؛ دوباره تولید کن.", show_alert=True)
            return
        await state.update_data(variant=variant, photo_id=None)
        await state.set_state(AdminCampaign.waiting_photo)
        rows = [[("🎨 ساخت تصویر با AI", "adm_camp_genimg")]] if channel_ai.image_configured(db) else []
        await call.message.answer(
            "🖼 عکس پست را بفرست، یا اگر پست بدون عکس می‌خواهی دکمه‌ی زیر را بزن.",
            reply_markup=_kb(*rows, [("📝 بدون عکس", "adm_camp_nophoto")], [("❌ لغو", "adm_camp_cancel")]),
        )
        await call.answer()

    async def _after_photo(target: Message, state: FSMContext, bot: Bot):
        channel = await asyncio.to_thread(db.get_setting, _CHANNEL_SETTING, "")
        if channel:
            await state.update_data(channel_id=channel)
            await _show_preview(target, state, bot)
        else:
            await _ask_channel(target, state)

    @router.message(AdminCampaign.waiting_photo, F.photo)
    async def msg_photo(message: Message, state: FSMContext, bot: Bot):
        if not senior_admin_only(message.from_user.id):
            await state.clear()
            return
        await state.update_data(photo_id=message.photo[-1].file_id)
        await _after_photo(message, state, bot)

    @router.callback_query(F.data == "adm_camp_nophoto")
    async def cb_nophoto(call: CallbackQuery, state: FSMContext, bot: Bot):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.update_data(photo_id=None)
        await call.answer()
        await _after_photo(call.message, state, bot)

    @router.callback_query(F.data == "adm_camp_genimg")
    async def cb_genimg(call: CallbackQuery, state: FSMContext, bot: Bot):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        variant = (await state.get_data()).get("variant")
        if not variant:
            await call.answer("ابتدا یک نسخه انتخاب کن.", show_alert=True)
            return
        await call.answer()
        status = await call.message.answer("🎨 در حال ساخت تصویر با AI (ممکن است چند دقیقه طول بکشد)...")
        try:
            raw, source = await channel_ai.generate_image(db, variant.get("image_prompt") or "")
        except Exception as exc:
            _log.warning("ساخت تصویر ناموفق بود: %s", exc)
            await status.edit_text(
                "❌ ساخت تصویر انجام نشد: " + html.escape(str(exc)),
                reply_markup=_kb([("🔄 تلاش دوباره", "adm_camp_genimg")], [("📝 بدون عکس", "adm_camp_nophoto")], [("❌ لغو", "adm_camp_cancel")]),
            )
            return
        try:
            await status.delete()
        except Exception:
            pass
        sent = await call.message.answer_photo(BufferedInputFile(raw, filename="post.jpg"), caption="🎨 تصویر ساخته‌شده: " + source)
        await state.update_data(photo_id=sent.photo[-1].file_id)
        await _after_photo(call.message, state, bot)

    async def _ask_channel(target: Message, state: FSMContext):
        await state.set_state(AdminCampaign.waiting_channel)
        await target.answer(
            "📢 آیدی کانال را بفرست (مثل <code>-1001234567890</code> یا <code>@channel_username</code>) "
            "یا یک پست از همان کانال را فوروارد کن.\nبات باید در کانال ادمین با دسترسی ارسال پیام باشد.",
            reply_markup=_cancel_kb(),
        )

    @router.callback_query(F.data == "adm_camp_channel")
    async def cb_channel(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await call.answer()
        await _ask_channel(call.message, state)

    @router.message(AdminCampaign.waiting_channel)
    async def msg_channel(message: Message, state: FSMContext, bot: Bot):
        if not senior_admin_only(message.from_user.id):
            await state.clear()
            return
        origin = getattr(message, "forward_origin", None)
        channel = None
        if origin is not None and getattr(origin, "chat", None) is not None:
            channel = str(origin.chat.id)
        else:
            raw = (message.text or "").strip().translate(_DIGITS)
            if _CHANNEL_RE.match(raw):
                channel = raw
        if not channel:
            await message.answer("آیدی نامعتبر بود. آیدی عددی (شروع با -100) یا @username بفرست یا یک پست کانال را فوروارد کن.", reply_markup=_cancel_kb())
            return
        try:
            chat = await bot.get_chat(channel)
            if chat.type != "channel":
                raise ValueError("این چت کانال نیست.")
        except Exception as exc:
            await message.answer("❌ کانال پیدا نشد یا بات به آن دسترسی ندارد: " + html.escape(str(exc)), reply_markup=_cancel_kb())
            return
        await asyncio.to_thread(db.set_setting, _CHANNEL_SETTING, str(chat.id))
        await state.update_data(channel_id=str(chat.id))
        await _show_preview(message, state, bot)

    async def _show_preview(target: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        await state.set_state(AdminCampaign.confirming)
        await target.answer("👀 پیش‌نمایش پست (دقیقاً همین به کانال می‌رود):")
        try:
            await _send_post(bot, target.chat.id, data)
        except Exception as exc:
            await target.answer("❌ ساخت پیش‌نمایش ناموفق بود: " + html.escape(str(exc)), reply_markup=_kb([("⬅️ بازگشت", _BACK)]))
            await state.clear()
            return
        image_rows = [[("🎨 تصویر جدید با AI", "adm_camp_genimg")]] if channel_ai.image_configured(db) else []
        await target.answer(
            "این پست به کانال ارسال شود؟",
            reply_markup=_kb(
                [("📣 ارسال به کانال", "adm_camp_send")],
                *image_rows,
                [("📢 تغییر کانال", "adm_camp_channel"), ("🔄 نسخه‌ی دیگر", "adm_camp_regen")],
                [("❌ لغو", "adm_camp_cancel")],
            ),
        )

    @router.callback_query(F.data == "adm_camp_send")
    async def cb_send(call: CallbackQuery, state: FSMContext, bot: Bot):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        data = await state.get_data()
        if not data.get("variant") or not data.get("channel_id"):
            await call.answer("اطلاعات پست کامل نیست؛ از اول شروع کن.", show_alert=True)
            return
        await state.clear()
        try:
            await _send_post(bot, data["channel_id"], data)
        except Exception as exc:
            await call.message.answer(
                "❌ ارسال به کانال ناموفق بود: " + html.escape(str(exc)) + "\n(احتمالاً بات ادمین کانال نیست یا دسترسی ارسال پیام ندارد)",
                reply_markup=_kb([("⬅️ بازگشت", _BACK)]),
            )
            await call.answer()
            return
        param = campaign_ai.start_param_for(data["variant"]["deeplink"]) or "-"
        await asyncio.to_thread(
            db.log_admin_action, call.from_user.id, "ai_channel_post", f"پست کانال با AI ارسال شد | دیپ‌لینک: {param}",
        )
        await call.message.answer("✅ پست در کانال ارسال شد.", reply_markup=_kb([("⬅️ بازگشت", _BACK)]))
        await call.answer()

    def _chai_text() -> str:
        has_key = bool(channel_ai.jarvis_keys(db))
        return (
            "⚙️ <b>مدل‌های AI کانال</b>\n"
            "جدا از دستیار پشتیبانی، دستیار ادمین و بقیه‌ی ایجنت‌ها؛ تغییر این بخش روی آن‌ها اثری ندارد.\n\n"
            f"🔑 کلید Jarvis: {'✅ ثبت شده' if has_key else '❌ ثبت نشده'}\n\n"
            "📝 <b>مدل متن</b>\n"
            f"مسیر: {channel_ai.TEXT_MODE_LABELS[channel_ai.text_mode(db)]}\n"
            f"مدل Jarvis: <code>{html.escape(channel_ai.jarvis_text_model(db))}</code>\n\n"
            "🎨 <b>مدل تصویر</b>\n"
            f"مسیر: {channel_ai.IMAGE_MODE_LABELS[channel_ai.image_mode(db)]}\n"
            f"مدل Jarvis: <code>{html.escape(channel_ai.jarvis_image_model(db))}</code>\n"
            f"مدل Gemini: <code>{html.escape(channel_ai.gemini_image_model(db))}</code>"
        )

    def _chai_kb() -> InlineKeyboardMarkup:
        return _kb(
            [("🔑 کلید Jarvis", "adm_chai_key")],
            [("📝 مدل متن", "adm_chai_tmodel"), ("🎨 مدل تصویر", "adm_chai_imodel")],
            [("🔀 مسیر متن", "adm_chai_tmode"), ("🔀 مسیر تصویر", "adm_chai_imode")],
            [("🧪 تست متن", "adm_chai_ttest"), ("🧪 تست تصویر (از اعتبار کم می‌شود)", "adm_chai_itest")],
            [("⬅️ بازگشت", _BACK)],
        )

    def _chai_back_kb() -> InlineKeyboardMarkup:
        return _kb([("⬅️ بازگشت", "adm_chai")])

    async def _show_chai(target: Message, edit: bool = True):
        if edit:
            try:
                await target.edit_text(_chai_text(), reply_markup=_chai_kb())
                return
            except Exception:
                pass
        await target.answer(_chai_text(), reply_markup=_chai_kb())

    async def _chai_log(admin_id: int, detail: str):
        await asyncio.to_thread(db.log_admin_action, admin_id, "channel_ai_change", detail)

    @router.callback_query(F.data == "adm_chai")
    async def cb_chai(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await _show_chai(call.message)
        await call.answer()

    @router.callback_query(F.data == "adm_chai_tmode")
    async def cb_chai_tmode(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        modes = channel_ai.TEXT_MODES
        new = modes[(modes.index(channel_ai.text_mode(db)) + 1) % len(modes)]
        await asyncio.to_thread(db.set_setting, "channel_text_provider", new)
        await _chai_log(call.from_user.id, f"مسیر متن کانال: {new}")
        await _show_chai(call.message)
        await call.answer()

    @router.callback_query(F.data == "adm_chai_imode")
    async def cb_chai_imode(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        modes = channel_ai.IMAGE_MODES
        new = modes[(modes.index(channel_ai.image_mode(db)) + 1) % len(modes)]
        await asyncio.to_thread(db.set_setting, "channel_image_provider", new)
        await _chai_log(call.from_user.id, f"مسیر تصویر کانال: {new}")
        await _show_chai(call.message)
        await call.answer()

    @router.callback_query(F.data == "adm_chai_key")
    async def cb_chai_key(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.set_state(AdminChannelAI.waiting_key)
        await call.message.answer(
            "🔑 کلید(های) Jarvis را بفرست؛ هر خط یک کلید (با pmai_ شروع می‌شود). بعد از ذخیره، پیام تو پاک می‌شود.\n"
            "برای حذف کلید: <code>-</code>",
            reply_markup=_chai_back_kb(),
        )
        await call.answer()

    @router.message(AdminChannelAI.waiting_key, F.text)
    async def msg_chai_key(message: Message, state: FSMContext):
        if not senior_admin_only(message.from_user.id):
            await state.clear()
            return
        raw = (message.text or "").strip()
        try:
            await message.delete()
        except Exception:
            pass
        keys = [] if raw == "-" else list(dict.fromkeys(k.strip() for k in raw.replace(",", "\n").splitlines() if k.strip()))
        if raw != "-" and not keys:
            await message.answer("کلیدی پیدا نشد؛ دوباره بفرست.", reply_markup=_chai_back_kb())
            return
        base = channel_ai.jarvis_base(db)
        rejected = [str(i) for i, key in enumerate(keys, 1) if not (await channel_ai.check_jarvis_key(base, key))[0]]
        if rejected:
            await message.answer(
                "❌ Jarvis این کلیدها را رد کرد (شماره‌ی خط): " + ", ".join(rejected) + "\nکلید را بررسی و دوباره بفرست.",
                reply_markup=_chai_back_kb(),
            )
            return
        await asyncio.to_thread(db.set_setting, "jarvis_api_key", "\n".join(keys))
        await _chai_log(message.from_user.id, "کلید Jarvis ذخیره شد" if keys else "کلید Jarvis حذف شد")
        await state.clear()
        await _show_chai(message, edit=False)

    async def _ask_model(call: CallbackQuery, state: FSMContext, kind: str):
        text_ids, image_ids = [], []
        try:
            text_ids, image_ids = await channel_ai.list_jarvis_models(db)
        except Exception as exc:
            _log.warning("دریافت فهرست مدل‌های Jarvis ناموفق بود: %s", exc)
        ids = text_ids if kind == "text" else image_ids
        current = channel_ai.jarvis_text_model(db) if kind == "text" else channel_ai.jarvis_image_model(db)
        title = "📝 مدل متن" if kind == "text" else "🎨 مدل تصویر"
        listing = ("\n\nمدل‌های موجود در Jarvis:\n" + "\n".join(f"<code>{html.escape(i)}</code>" for i in ids[:15])) if ids else ""
        await state.set_state(AdminChannelAI.waiting_text_model if kind == "text" else AdminChannelAI.waiting_image_model)
        await call.message.answer(
            f"{title}\nمدل فعلی: <code>{html.escape(current)}</code>{listing}\n\n"
            "شناسه‌ی دقیق مدل را بفرست؛ برای برگشت به پیش‌فرض: <code>-</code>",
            reply_markup=_chai_back_kb(),
        )
        await call.answer()

    @router.callback_query(F.data == "adm_chai_tmodel")
    async def cb_chai_tmodel(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await _ask_model(call, state, "text")

    @router.callback_query(F.data == "adm_chai_imodel")
    async def cb_chai_imodel(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await _ask_model(call, state, "image")

    async def _save_model(message: Message, state: FSMContext, kind: str):
        if not senior_admin_only(message.from_user.id):
            await state.clear()
            return
        value = "" if (message.text or "").strip() == "-" else (message.text or "").strip()
        if value and any(ch.isspace() for ch in value):
            await message.answer("شناسه‌ی مدل نباید فاصله داشته باشد.", reply_markup=_chai_back_kb())
            return
        if kind == "text" and value and not channel_ai.is_text_model(value):
            await message.answer("این شناسه مدل متنی نیست (شامل image/embed/tts و مانند آن است).", reply_markup=_chai_back_kb())
            return
        key = "jarvis_text_model" if kind == "text" else "jarvis_image_model"
        await asyncio.to_thread(db.set_setting, key, value)
        await _chai_log(message.from_user.id, f"{key}: {value or 'پیش‌فرض'}")
        await state.clear()
        await _show_chai(message, edit=False)

    @router.message(AdminChannelAI.waiting_text_model, F.text)
    async def msg_chai_text_model(message: Message, state: FSMContext):
        await _save_model(message, state, "text")

    @router.message(AdminChannelAI.waiting_image_model, F.text)
    async def msg_chai_image_model(message: Message, state: FSMContext):
        await _save_model(message, state, "image")

    @router.callback_query(F.data == "adm_chai_ttest")
    async def cb_chai_ttest(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await call.answer("⏳ در حال تست...")
        try:
            _data, source = await channel_ai.ask_json(db, 'فقط این JSON را برگردان: {"ok": true}', "ping")
        except Exception as exc:
            await call.message.answer("❌ تست متن ناموفق بود: " + html.escape(str(exc)), reply_markup=_chai_back_kb())
            return
        await call.message.answer(f"✅ مدل متن کانال کار می‌کند: <code>{html.escape(source)}</code>", reply_markup=_chai_back_kb())

    @router.callback_query(F.data == "adm_chai_itest")
    async def cb_chai_itest(call: CallbackQuery):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await call.answer("⏳ در حال ساخت تصویر آزمایشی...")
        try:
            raw, source = await channel_ai.generate_image(db, "")
        except Exception as exc:
            await call.message.answer("❌ تست تصویر ناموفق بود: " + html.escape(str(exc)), reply_markup=_chai_back_kb())
            return
        await call.message.answer_photo(BufferedInputFile(raw, filename="test.jpg"), caption="✅ مدل تصویر کانال کار می‌کند: " + source, reply_markup=_chai_back_kb())

    @router.callback_query(F.data == "adm_camp_cancel")
    async def cb_cancel(call: CallbackQuery, state: FSMContext):
        if not senior_admin_only(call.from_user.id):
            return await deny_mid(call)
        await state.clear()
        await call.message.answer("لغو شد.", reply_markup=_kb([("⬅️ بازگشت", _BACK)]))
        await call.answer()
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
