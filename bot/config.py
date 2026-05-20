import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _parse_chat_id(raw: str) -> int | str:
    raw = raw.strip()
    if raw.startswith("@"):
        return raw
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


def _parse_owners(raw: str) -> set[int]:
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_user_ids: set[int]
    aggregator_chat: int | str
    trigger_emoji: str
    price_stars_30d: int
    db_path: str


def load_settings() -> Settings:
    bot_token = os.environ["BOT_TOKEN"]
    return Settings(
        bot_token=bot_token,
        owner_user_ids=_parse_owners(os.environ.get("OWNER_USER_ID", "")),
        aggregator_chat=_parse_chat_id(os.environ["AGGREGATOR_CHANNEL_ID"]),
        trigger_emoji=os.environ.get("TRIGGER_EMOJI", "🤑"),
        price_stars_30d=int(os.environ.get("PRICE_STARS_30D", "500")),
        db_path=os.environ.get("DB_PATH", "reposter.db"),
    )
