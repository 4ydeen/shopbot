# -*- coding: utf-8 -*-
"""
رجیستری سراسری «کاستوم‌سازی دکمه‌ها» برای تب مستقل پنل وب.

این فایل تنها جایی است که پنل وب برای ساختن/ذخیره‌ی تب «دکمه‌ها» به آن نیاز
دارد. اگر بعداً دکمه‌ی جدیدی به بات اضافه شود:
  - اگر داخل منوی اصلی است: یک ورودی به MENU_BUTTON_META در database.py اضافه کن.
  - اگر داخل پنل مدیریت است: یک ورودی به ADMIN_PANEL_ITEMS/ADMIN_PANEL_CATEGORIES
    در keyboards.py اضافه کن.
  - اگر یک دکمه‌ی ثابت جدید در مسیر خرید/حساب کاربری/پرداخت است: به متادیتای
    مربوطه (BUYFLOW_META / ACCOUNT_HUB_META / PAYMENT_METHOD_META) در
    database.py اضافه کن.
در هر سه حالت، تب «دکمه‌ها»ی پنل وب بدون هیچ تغییری در این فایل یا فرانت‌اند،
آیتم جدید را خودکار نشان می‌دهد.
"""

import database as dbmod
import keyboards as kb

STYLE_CHOICES = ("", "primary", "success", "danger")


def _style_options():
    return [
        {"value": "", "label": "پیش‌فرض (خاکستری)"},
        {"value": "primary", "label": "آبی"},
        {"value": "success", "label": "سبز"},
        {"value": "danger", "label": "قرمز"},
    ]


def build_registry(db) -> dict:
    # نکته: منوی اصلی بات (کیبورد پایین/شیشه‌ای) از قبل یک ویرایشگر
    # درگ‌اند‌دراپ کامل (متن + رنگ + ترتیب + چیدمان ردیف‌ها) در تب «تنظیمات و
    # برندینگ ← چیدمان منو» دارد؛ برای جلوگیری از دوباره‌کاری و دو محل مجزا
    # برای یک چیز، اینجا تکرار نشده - این تب مکمل آن است، نه جایگزینش.
    groups = []

    # -------------------------------------------------------- پنل مدیریت: دسته‌ها
    cat_default_order = [c[0] for c in kb.ADMIN_PANEL_CATEGORIES]
    cat_label_by_key = {c[0]: c[1] for c in kb.ADMIN_PANEL_CATEGORIES}
    cat_order = db.get_custom_order("admin_categories", cat_default_order)
    cat_items = []
    for key in cat_order:
        default_label = cat_label_by_key.get(key)
        if default_label is None:
            continue
        cat_items.append({
            "key": key, "label": default_label, "has_text": True, "has_style": True,
            "text": db.get_setting(f"catlbl_{key}", default_label),
            "style": db.get_setting(f"catlbl_{key}_style", ""),
            "row_break_before": None,
        })
    groups.append({
        "key": "admin_categories", "label": "پنل مدیریت — دسته‌های اصلی",
        "reorderable": True, "supports_row_break": False, "items": cat_items,
    })

    # -------------------------------------------------- پنل مدیریت: آیتم‌های هر دسته
    for cat_key, cat_label, default_item_keys in kb.ADMIN_PANEL_CATEGORIES:
        order = db.get_custom_order(f"admin_items__{cat_key}", default_item_keys)
        items = []
        for key in order:
            if key not in default_item_keys or key in kb._EXTRA_PANEL_ITEM_LABELS:
                continue
            label, _cb = kb._admin_item_label_and_cb(key)
            items.append({
                "key": key, "label": label, "has_text": True, "has_style": True,
                "text": db.get_setting(f"{key}_label", label),
                "style": db.get_setting(f"{key}_style", ""),
                "row_break_before": None,
            })
        if items:
            groups.append({
                "key": f"admin_items__{cat_key}", "label": f"پنل مدیریت — {cat_label}",
                "reorderable": True, "supports_row_break": False, "items": items,
            })

    # ---------------------------------------------------------------- مسیر خرید
    bf_items = []
    for key, meta in dbmod.BUYFLOW_META.items():
        bf_items.append({
            "key": key, "label": meta["label"], "has_text": True, "has_style": True,
            "text": db.get_setting(f"{key}_text", meta["default_text"]),
            "style": db.get_setting(f"{key}_style", ""),
            "row_break_before": None,
        })
    groups.append({
        "key": "buyflow", "label": "مسیر خرید — متن/رنگ دکمه‌های ثابت",
        "reorderable": False, "supports_row_break": False, "items": bf_items,
        "note": "این دکمه‌ها هرکدام جای ثابتی در مسیر خرید دارند؛ فقط متن و رنگشان اینجا قابل تغییر است.",
    })
    confirm_order = db.get_custom_order("buyflow_confirm", dbmod.DEFAULT_BUYFLOW_CONFIRM_ORDER)
    groups.append({
        "key": "buyflow_confirm", "label": "مسیر خرید — ترتیب «ادامه» و «کد تخفیف»",
        "reorderable": True, "supports_row_break": False,
        "items": [{
            "key": key, "label": dbmod.BUYFLOW_META[key]["label"],
            "has_text": False, "has_style": False, "text": None, "style": None, "row_break_before": None,
        } for key in confirm_order],
        "note": "دکمه‌ی «بازگشت» همیشه ردیف آخر ثابت می‌ماند.",
    })

    # ------------------------------------------------------------ حساب کاربری من
    acct_order = db.get_custom_order("account_hub", dbmod.DEFAULT_ACCOUNT_HUB_ORDER)
    acct_items = []
    for key in acct_order:
        meta = dbmod.ACCOUNT_HUB_META.get(key)
        if not meta:
            continue
        acct_items.append({
            "key": key, "label": meta["label"], "has_text": True, "has_style": True,
            "text": db.get_setting(f"{key}_text", meta["default_text"]),
            "style": db.get_setting(f"{key}_style", ""),
            "row_break_before": None,
        })
    groups.append({
        "key": "account_hub", "label": "حساب کاربری من",
        "reorderable": True, "supports_row_break": False, "items": acct_items,
    })

    # -------------------------------------------- روش‌های پرداخت + درگاه‌های سفارشی
    gateways = db.list_custom_gateways()
    gw_by_key = {f"customgw:{g['id']}": g for g in gateways}
    valid_keys = list(dbmod.DEFAULT_PAYMENT_METHOD_ORDER) + list(gw_by_key.keys())
    pm_order = db.get_custom_order("payment_methods", valid_keys)
    pm_items = []
    for key in pm_order:
        if key in dbmod.PAYMENT_METHOD_META:
            meta = dbmod.PAYMENT_METHOD_META[key]
            pm_items.append({
                "key": key, "label": meta["label"], "has_text": True, "has_style": True,
                "text": db.get_setting(f"paymeth_{key}_text", meta["default_text"]),
                "style": db.get_setting(f"paymeth_{key}_style", ""),
                "row_break_before": None,
            })
        elif key in gw_by_key:
            gw = gw_by_key[key]
            default_text = f"💠 {gw['name']} (تایید آنی)"
            pm_items.append({
                "key": key, "label": f"درگاه سفارشی: {gw['name']}", "has_text": True, "has_style": True,
                "text": db.get_setting(f"paymeth_customgw_{gw['id']}_text", default_text),
                "style": db.get_setting(f"paymeth_customgw_{gw['id']}_style", ""),
                "row_break_before": None,
            })
    groups.append({
        "key": "payment_methods", "label": "روش‌های پرداخت (شامل درگاه‌های سفارشی)",
        "reorderable": True, "supports_row_break": False, "items": pm_items,
        "note": "درگاه‌های سفارشی خودکار وارد این لیست می‌شوند - همین‌جا هم قابل جابجایی و رنگ‌آمیزی‌اند.",
    })

    return {"groups": groups, "style_options": _style_options()}


def _group_valid_keys(db, group: str):
    if group == "main_menu":
        return list(dbmod.MENU_BUTTON_META.keys())
    if group == "admin_categories":
        return [c[0] for c in kb.ADMIN_PANEL_CATEGORIES]
    if group.startswith("admin_items__"):
        cat_key = group.split("__", 1)[1]
        return next((items for k, _, items in kb.ADMIN_PANEL_CATEGORIES if k == cat_key), [])
    if group == "buyflow":
        return list(dbmod.BUYFLOW_META.keys())
    if group == "buyflow_confirm":
        return list(dbmod.DEFAULT_BUYFLOW_CONFIRM_ORDER)
    if group == "account_hub":
        return list(dbmod.ACCOUNT_HUB_META.keys())
    if group == "payment_methods":
        gateways = db.list_custom_gateways()
        return list(dbmod.DEFAULT_PAYMENT_METHOD_ORDER) + [f"customgw:{g['id']}" for g in gateways]
    return []


_TEXT_ONLY_GROUPS = {"buyflow_confirm"}  # این گروه‌ها فقط ترتیب دارند، متن/رنگ ندارند


def update_item(db, group: str, key: str, text: str = None, style: str = None):
    valid = _group_valid_keys(db, group)
    if key not in valid:
        raise ValueError("کلید نامعتبر برای این گروه")
    if group in _TEXT_ONLY_GROUPS:
        raise ValueError("این گروه فقط قابل جابجایی است، متن/رنگ ندارد")
    if style is not None and style not in STYLE_CHOICES:
        raise ValueError("رنگ نامعتبر")

    if text is not None:
        text = text.strip()
        if not text:
            raise ValueError("متن دکمه نمی‌تواند خالی باشد")
        if group == "main_menu":
            db.set_setting(key, text)
        elif group == "admin_categories":
            db.set_setting(f"catlbl_{key}", text)
        elif group.startswith("admin_items__"):
            db.set_setting(f"{key}_label", text)
        elif group in ("buyflow", "account_hub"):
            db.set_setting(f"{key}_text", text)
        elif group == "payment_methods":
            if key.startswith("customgw:"):
                gw_id = key.split(":", 1)[1]
                db.set_setting(f"paymeth_customgw_{gw_id}_text", text)
            else:
                db.set_setting(f"paymeth_{key}_text", text)
        else:
            raise ValueError("این گروه متن قابل ویرایش ندارد")

    if style is not None:
        if group == "main_menu":
            db.set_setting(f"{key}_style", style)
        elif group == "admin_categories":
            db.set_setting(f"catlbl_{key}_style", style)
        elif group.startswith("admin_items__"):
            db.set_setting(f"{key}_style", style)
        elif group in ("buyflow", "account_hub"):
            db.set_setting(f"{key}_style", style)
        elif group == "payment_methods":
            if key.startswith("customgw:"):
                gw_id = key.split(":", 1)[1]
                db.set_setting(f"paymeth_customgw_{gw_id}_style", style)
            else:
                db.set_setting(f"paymeth_{key}_style", style)
        else:
            raise ValueError("این گروه رنگ قابل ویرایش ندارد")


def update_order(db, group: str, order: list):
    valid = _group_valid_keys(db, group)
    if not valid:
        raise ValueError("گروه نامعتبر یا قابل جابجایی نیست")
    if group == "main_menu":
        db.set_menu_order(order)
        return
    db.set_custom_order(group, order, valid)


def set_row_break(db, key: str, value: bool):
    """فقط برای منوی اصلی: مشخص می‌کند آیا این دکمه ردیف تازه‌ای شروع می‌کند یا
    به ردیفِ دکمه‌ی قبلی‌اش می‌چسبد."""
    if key not in dbmod.MENU_BUTTON_META:
        raise ValueError("کلید نامعتبر")
    order = db.get_menu_order()
    breaks = set(db.get_menu_row_breaks() or [])
    if value:
        breaks.add(key)
    else:
        breaks.discard(key)
    db.set_menu_row_breaks([k for k in order if k in breaks])
