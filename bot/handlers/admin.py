"""
Admin (aggregator owner) commands.
Owners listed via OWNER_USER_ID env can manage every client manually.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import db
from ..config import Settings
from ..keyboards import admin_client_card, admin_clients_list, admin_main_menu

router = Router(name="admin")


def _is_owner(user_id: int, settings: Settings) -> bool:
    return user_id in settings.owner_user_ids


def _client_card_text(client, default_trigger: str) -> str:
    title = client["chat_title"] or client["chat_username"] or str(client["chat_id"])
    paid = client["paid_until"] or "—"
    active = "🟢 active" if db.subscription_active(client) else "⚪️ inactive"
    return (
        f"<b>{title}</b>\n"
        f"chat_id: <code>{client['chat_id']}</code>\n"
        f"owner: <code>{client['owner_user_id']}</code>\n"
        f"forward_mode: <code>{client['forward_mode']}</code>\n"
        f"trigger: {client['trigger_emoji'] or default_trigger}\n"
        f"paid_until: <code>{paid}</code>\n"
        f"status: {active}"
    )


@router.message(Command("admin"), F.chat.type == "private")
async def cmd_admin(message: Message, settings: Settings):
    if not _is_owner(message.from_user.id, settings):
        return
    await message.answer("🛠 Админка", reply_markup=admin_main_menu())


@router.callback_query(F.data == "admin:back")
async def cb_back(cq: CallbackQuery, settings: Settings):
    if not _is_owner(cq.from_user.id, settings):
        await cq.answer()
        return
    await cq.message.edit_text("🛠 Админка", reply_markup=admin_main_menu())
    await cq.answer()


@router.callback_query(F.data == "admin:clients")
async def cb_clients(cq: CallbackQuery, settings: Settings):
    if not _is_owner(cq.from_user.id, settings):
        await cq.answer()
        return
    clients = await db.list_all_clients()
    if not clients:
        await cq.message.edit_text("Клиентов пока нет.", reply_markup=admin_main_menu())
    else:
        await cq.message.edit_text(
            f"📋 Клиенты ({len(clients)}):",
            reply_markup=admin_clients_list(clients),
        )
    await cq.answer()


@router.callback_query(F.data == "admin:stats")
async def cb_stats(cq: CallbackQuery, settings: Settings):
    if not _is_owner(cq.from_user.id, settings):
        await cq.answer()
        return
    clients = await db.list_all_clients()
    active = sum(1 for c in clients if db.subscription_active(c))
    await cq.message.edit_text(
        f"📊 Всего клиентов: {len(clients)}\n"
        f"С активной подпиской: {active}",
        reply_markup=admin_main_menu(),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:client:"))
async def cb_client(cq: CallbackQuery, settings: Settings):
    if not _is_owner(cq.from_user.id, settings):
        await cq.answer()
        return
    client_id = int(cq.data.split(":")[2])
    client = await db.get_client(client_id)
    if not client:
        await cq.answer("Не найден", show_alert=True)
        return
    await cq.message.edit_text(
        _client_card_text(client, settings.trigger_emoji),
        reply_markup=admin_client_card(
            client_id,
            db.subscription_active(client),
            client["forward_mode"],
        ),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:toggle:"))
async def cb_toggle(cq: CallbackQuery, settings: Settings):
    if not _is_owner(cq.from_user.id, settings):
        await cq.answer()
        return
    client_id = int(cq.data.split(":")[2])
    client = await db.get_client(client_id)
    if not client:
        await cq.answer("Не найден", show_alert=True)
        return
    await db.set_active(client_id, not bool(client["is_active"]))
    client = await db.get_client(client_id)
    await cq.message.edit_text(
        _client_card_text(client, settings.trigger_emoji),
        reply_markup=admin_client_card(
            client_id,
            db.subscription_active(client),
            client["forward_mode"],
        ),
    )
    await cq.answer("Готово")


@router.callback_query(F.data.startswith("admin:extend:"))
async def cb_extend(cq: CallbackQuery, settings: Settings):
    if not _is_owner(cq.from_user.id, settings):
        await cq.answer()
        return
    _, _, client_id_s, days_s = cq.data.split(":")
    client_id = int(client_id_s)
    days = int(days_s)
    new_until = await db.extend_subscription(client_id, days)
    client = await db.get_client(client_id)
    await cq.message.edit_text(
        _client_card_text(client, settings.trigger_emoji),
        reply_markup=admin_client_card(
            client_id,
            db.subscription_active(client),
            client["forward_mode"],
        ),
    )
    await cq.answer(f"+{days} дней до {new_until.date().isoformat()}")


@router.callback_query(F.data.startswith("admin:mode:"))
async def cb_mode(cq: CallbackQuery, settings: Settings):
    if not _is_owner(cq.from_user.id, settings):
        await cq.answer()
        return
    _, _, client_id_s, mode = cq.data.split(":")
    if mode not in ("forward", "copy"):
        await cq.answer("Неверный режим", show_alert=True)
        return
    client_id = int(client_id_s)
    await db.set_forward_mode(client_id, mode)
    client = await db.get_client(client_id)
    await cq.message.edit_text(
        _client_card_text(client, settings.trigger_emoji),
        reply_markup=admin_client_card(
            client_id,
            db.subscription_active(client),
            client["forward_mode"],
        ),
    )
    await cq.answer(f"Режим: {mode}")


@router.callback_query(F.data.startswith("admin:delete:"))
async def cb_delete(cq: CallbackQuery, settings: Settings):
    if not _is_owner(cq.from_user.id, settings):
        await cq.answer()
        return
    client_id = int(cq.data.split(":")[2])
    await db.delete_client(client_id)
    clients = await db.list_all_clients()
    await cq.message.edit_text(
        f"Удалён.\n\n📋 Клиенты ({len(clients)}):" if clients else "Удалён. Клиентов нет.",
        reply_markup=admin_clients_list(clients) if clients else admin_main_menu(),
    )
    await cq.answer("Удалён")
