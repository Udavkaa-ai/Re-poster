"""
Watches channel posts in client channels.
If the post contains the trigger emoji in its text/caption AND the client
has an active subscription, republishes the post to the aggregator channel
using either forward_message or copy_message based on client's forward_mode.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.types import Message

from .. import db
from ..config import Settings

logger = logging.getLogger(__name__)
router = Router(name="forwarder")


def _matches_trigger(text: str, trigger: str) -> bool:
    return bool(text) and trigger in text


@router.channel_post()
async def on_channel_post(message: Message, bot: Bot, settings: Settings):
    chat_id = message.chat.id

    client = await db.get_client_by_chat(chat_id)
    if not client:
        return

    if not db.subscription_active(client):
        logger.debug("Skip %s/%s: subscription inactive", chat_id, message.message_id)
        return

    trigger = client["trigger_emoji"] or settings.trigger_emoji
    body = message.text or message.caption or ""
    if not _matches_trigger(body, trigger):
        return

    if await db.is_processed(chat_id, message.message_id):
        return

    target = settings.aggregator_chat
    mode = client["forward_mode"]
    try:
        if mode == "copy":
            await bot.copy_message(
                chat_id=target,
                from_chat_id=chat_id,
                message_id=message.message_id,
            )
        else:
            await bot.forward_message(
                chat_id=target,
                from_chat_id=chat_id,
                message_id=message.message_id,
            )
        await db.mark_processed(chat_id, message.message_id)
        logger.info(
            "Reposted %s/%s -> %s (mode=%s)",
            chat_id, message.message_id, target, mode,
        )
    except Exception:
        logger.exception("Failed to repost %s/%s", chat_id, message.message_id)
