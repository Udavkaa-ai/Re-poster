"""
Client-facing flow: /start in private chat, channel registration,
forward/copy toggle, payment entry point.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import db
from ..config import Settings
from ..keyboards import client_channel_menu, client_main_menu

logger = logging.getLogger(__name__)
router = Router(name="client")


class AddChannel(StatesGroup):
    waiting_forward = State()


HELP_TEXT = (
    "Я перепощу твой пост в канал-агрегатор, когда в его тексте появится "
    "триггер-эмодзи {trigger}.\n\n"
    "<b>Как подключить канал:</b>\n"
    "1. Добавь меня администратором в свой канал.\n"
    "2. Нажми «➕ Добавить канал» и перешли мне любой пост из этого канала.\n"
    "3. Оплати размещение.\n"
    "4. Публикуй посты с {trigger} в тексте — они автоматически попадут в агрегатор.\n\n"
    "По умолчанию используется forward (с указанием источника). "
    "В настройках канала можешь переключить на copy — пост будет выглядеть "
    "как собственный пост агрегатора."
)


def _client_summary(client, default_trigger: str) -> str:
    title = client["chat_title"] or client["chat_username"] or str(client["chat_id"])
    trigger = client["trigger_emoji"] or default_trigger
    paid_until = client["paid_until"]
    if paid_until and db.subscription_active(client):
        status = f"✅ Активна до {paid_until[:10]}"
    elif paid_until:
        status = f"⛔️ Истекла {paid_until[:10]}"
    else:
        status = "⏳ Не оплачена"
    return (
        f"📺 <b>{title}</b>\n"
        f"Статус: {status}\n"
        f"Режим: <code>{client['forward_mode']}</code>\n"
        f"Триггер: {trigger}"
    )


async def _send_menu(message: Message, settings: Settings):
    rows = await db.list_clients_for_owner(message.from_user.id)
    client = rows[0] if rows else None
    if client:
        await message.answer(
            _client_summary(client, settings.trigger_emoji),
            reply_markup=client_main_menu(has_channel=True),
        )
    else:
        await message.answer(
            HELP_TEXT.format(trigger=settings.trigger_emoji),
            reply_markup=client_main_menu(has_channel=False),
        )


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext, settings: Settings):
    await state.clear()
    await _send_menu(message, settings)


@router.message(Command("help"), F.chat.type == "private")
async def cmd_help(message: Message, settings: Settings):
    await message.answer(HELP_TEXT.format(trigger=settings.trigger_emoji))


@router.callback_query(F.data == "client:help")
async def cb_help(cq: CallbackQuery, settings: Settings):
    await cq.message.edit_text(
        HELP_TEXT.format(trigger=settings.trigger_emoji),
        reply_markup=client_main_menu(has_channel=False),
    )
    await cq.answer()


@router.callback_query(F.data == "client:back")
async def cb_back(cq: CallbackQuery, settings: Settings):
    rows = await db.list_clients_for_owner(cq.from_user.id)
    client = rows[0] if rows else None
    if client:
        await cq.message.edit_text(
            _client_summary(client, settings.trigger_emoji),
            reply_markup=client_main_menu(has_channel=True),
        )
    else:
        await cq.message.edit_text(
            HELP_TEXT.format(trigger=settings.trigger_emoji),
            reply_markup=client_main_menu(has_channel=False),
        )
    await cq.answer()


@router.callback_query(F.data == "client:my_channel")
async def cb_my_channel(cq: CallbackQuery, settings: Settings):
    rows = await db.list_clients_for_owner(cq.from_user.id)
    if not rows:
        await cq.answer("Канал не найден", show_alert=True)
        return
    client = rows[0]
    await cq.message.edit_text(
        _client_summary(client, settings.trigger_emoji),
        reply_markup=client_channel_menu(client["id"], client["forward_mode"]),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("client:mode:"))
async def cb_set_mode(cq: CallbackQuery, settings: Settings):
    _, _, client_id_s, mode = cq.data.split(":")
    client_id = int(client_id_s)
    client = await db.get_client(client_id)
    if not client or client["owner_user_id"] != cq.from_user.id:
        await cq.answer("Нет доступа", show_alert=True)
        return
    if mode not in ("forward", "copy"):
        await cq.answer("Неверный режим", show_alert=True)
        return
    await db.set_forward_mode(client_id, mode)
    client = await db.get_client(client_id)
    await cq.message.edit_text(
        _client_summary(client, settings.trigger_emoji),
        reply_markup=client_channel_menu(client_id, mode),
    )
    await cq.answer(f"Режим: {mode}")


@router.callback_query(F.data == "client:add_channel")
async def cb_add_channel(cq: CallbackQuery, state: FSMContext, settings: Settings):
    await state.set_state(AddChannel.waiting_forward)
    await cq.message.edit_text(
        "Перешли мне любой пост из своего канала.\n\n"
        "Перед этим убедись, что я добавлен в этот канал администратором "
        "с правом «Post messages» — иначе репост работать не будет."
    )
    await cq.answer()


@router.message(AddChannel.waiting_forward, F.chat.type == "private")
async def on_forwarded_post(message: Message, state: FSMContext, bot: Bot, settings: Settings):
    fwd = message.forward_from_chat
    if not fwd or fwd.type != "channel":
        await message.answer("Это не пересланный пост из канала. Попробуй ещё раз.")
        return

    chat_id = fwd.id
    # Verify the bot is an admin in the channel.
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        if member.status not in ("administrator", "creator"):
            await message.answer(
                "Я не вижу себя администратором в этом канале. "
                "Добавь меня админом и пересылай пост снова."
            )
            return
    except Exception:
        logger.exception("get_chat_member failed for %s", chat_id)
        await message.answer(
            "Не получилось проверить права в канале. "
            "Убедись, что я добавлен туда администратором, и попробуй снова."
        )
        return

    await db.upsert_client(
        chat_id=chat_id,
        owner_user_id=message.from_user.id,
        chat_username=fwd.username,
        chat_title=fwd.title,
    )
    await state.clear()

    rows = await db.list_clients_for_owner(message.from_user.id)
    client = next((c for c in rows if c["chat_id"] == chat_id), rows[0])
    await message.answer(
        "✅ Канал привязан.\n\n" + _client_summary(client, settings.trigger_emoji),
        reply_markup=client_main_menu(has_channel=True),
    )
