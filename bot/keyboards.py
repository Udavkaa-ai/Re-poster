from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_main_menu(has_channel: bool, trial_days: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has_channel:
        b.button(text="📺 Мой канал", callback_data="client:my_channel")
        if trial_days > 0:
            b.button(text=f"🎁 Бесплатный тест ({trial_days} дн.)", callback_data="client:trial")
        b.button(text="💳 Оплатить размещение", callback_data="client:pay")
    else:
        b.button(text="➕ Добавить канал", callback_data="client:add_channel")
    b.button(text="ℹ️ Как это работает", callback_data="client:help")
    b.adjust(1)
    return b.as_markup()


def client_channel_menu(client_id: int, forward_mode: str, trial_days: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    label_forward = "✅ Forward" if forward_mode == "forward" else "Forward"
    label_copy = "✅ Copy" if forward_mode == "copy" else "Copy"
    b.button(text=label_forward, callback_data=f"client:mode:{client_id}:forward")
    b.button(text=label_copy, callback_data=f"client:mode:{client_id}:copy")
    if trial_days > 0:
        b.button(text=f"🎁 Тест ({trial_days} дн.)", callback_data="client:trial")
    b.button(text="💳 Оплатить / продлить", callback_data="client:pay")
    b.button(text="⬅️ Назад", callback_data="client:back")
    rows = (2, 1, 1, 1) if trial_days > 0 else (2, 1, 1)
    b.adjust(*rows)
    return b.as_markup()


def admin_main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📋 Клиенты", callback_data="admin:clients")
    b.button(text="📊 Статистика", callback_data="admin:stats")
    b.adjust(1)
    return b.as_markup()


def admin_clients_list(clients) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in clients:
        title = c["chat_title"] or c["chat_username"] or str(c["chat_id"])
        mark = "🟢" if c["is_active"] else "⚪️"
        b.button(text=f"{mark} {title}", callback_data=f"admin:client:{c['id']}")
    b.button(text="⬅️ Назад", callback_data="admin:back")
    b.adjust(1)
    return b.as_markup()


def admin_client_card(client_id: int, is_active: bool, forward_mode: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text="🚫 Деактивировать" if is_active else "✅ Активировать",
        callback_data=f"admin:toggle:{client_id}",
    )
    b.button(text="+30 дней", callback_data=f"admin:extend:{client_id}:30")
    b.button(text="+7 дней", callback_data=f"admin:extend:{client_id}:7")
    label_forward = "✅ Forward" if forward_mode == "forward" else "Forward"
    label_copy = "✅ Copy" if forward_mode == "copy" else "Copy"
    b.button(text=label_forward, callback_data=f"admin:mode:{client_id}:forward")
    b.button(text=label_copy, callback_data=f"admin:mode:{client_id}:copy")
    b.button(text="❌ Удалить", callback_data=f"admin:delete:{client_id}")
    b.button(text="⬅️ Назад", callback_data="admin:clients")
    b.adjust(1, 2, 2, 1, 1)
    return b.as_markup()


def confirm_keyboard(yes_data: str, no_data: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да", callback_data=yes_data)
    b.button(text="❌ Нет", callback_data=no_data)
    b.adjust(2)
    return b.as_markup()
