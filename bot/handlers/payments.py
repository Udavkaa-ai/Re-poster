"""
Telegram Stars payment flow.
Pricing: PRICE_STARS_30D in XTR for 30 days of subscription.
"""

from __future__ import annotations

import json
import logging

from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from .. import db
from ..config import Settings

logger = logging.getLogger(__name__)
router = Router(name="payments")

DAYS_PER_INVOICE = 30


@router.callback_query(F.data == "client:pay")
async def cb_pay(cq: CallbackQuery, bot: Bot, settings: Settings):
    rows = await db.list_clients_for_owner(cq.from_user.id)
    if not rows:
        await cq.answer("Сначала добавь канал", show_alert=True)
        return
    client = rows[0]

    payload = json.dumps({"client_id": client["id"], "days": DAYS_PER_INVOICE})
    await bot.send_invoice(
        chat_id=cq.from_user.id,
        title=f"Размещение в агрегаторе ({DAYS_PER_INVOICE} дней)",
        description=(
            f"Подписка на {DAYS_PER_INVOICE} дней для канала "
            f"{client['chat_title'] or client['chat_username'] or client['chat_id']}."
        ),
        payload=payload,
        provider_token="",  # empty for Telegram Stars
        currency="XTR",
        prices=[LabeledPrice(label=f"{DAYS_PER_INVOICE} days", amount=settings.price_stars_30d)],
    )
    await cq.answer()


@router.pre_checkout_query()
async def on_pre_checkout(pcq: PreCheckoutQuery, bot: Bot):
    try:
        data = json.loads(pcq.invoice_payload)
        client = await db.get_client(int(data["client_id"]))
        if not client:
            await bot.answer_pre_checkout_query(
                pcq.id, ok=False, error_message="Канал не найден"
            )
            return
        await bot.answer_pre_checkout_query(pcq.id, ok=True)
    except Exception:
        logger.exception("pre_checkout failed")
        await bot.answer_pre_checkout_query(
            pcq.id, ok=False, error_message="Ошибка при проверке платежа"
        )


@router.message(F.successful_payment)
async def on_payment_success(message: Message, settings: Settings):
    sp = message.successful_payment
    try:
        data = json.loads(sp.invoice_payload)
        client_id = int(data["client_id"])
        days = int(data.get("days", DAYS_PER_INVOICE))
    except Exception:
        logger.exception("bad payment payload: %s", sp.invoice_payload)
        await message.answer(
            "Платёж получен, но в нагрузке ошибка. Свяжись с поддержкой."
        )
        return

    new_until = await db.extend_subscription(client_id, days)
    await db.record_payment(
        client_id=client_id,
        user_id=message.from_user.id,
        amount=sp.total_amount,
        currency=sp.currency,
        days_added=days,
        payment_charge_id=sp.provider_payment_charge_id,
        telegram_payment_charge_id=sp.telegram_payment_charge_id,
    )
    await message.answer(
        f"✅ Оплата получена: {sp.total_amount} {sp.currency}.\n"
        f"Подписка активна до <b>{new_until.date().isoformat()}</b>."
    )
