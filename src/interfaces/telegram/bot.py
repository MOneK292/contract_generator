"""Telegram bot startup and polling."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiohttp import ThreadedResolver
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BotCommand

from src.core.contract_engine import ContractEngine
from src.core.exceptions import ContractGeneratorError
from src.interfaces.telegram.dispatcher import create_dispatcher
from src.services.config import AppConfig, TemplateCatalog


class TelegramStartupError(ContractGeneratorError):
    """Raised when Telegram cannot be started."""


@dataclass(frozen=True)
class TelegramApplication:
    """Created Telegram bot and dispatcher."""

    bot: Bot
    dispatcher: Dispatcher


_logger = logging.getLogger(__name__)


def create_bot(config: AppConfig) -> Bot:
    """Create a Telegram bot from AppConfig."""
    token = config.env.get("BOT_TOKEN", "").strip()
    if not token:
        raise TelegramStartupError("BOT_TOKEN is missing in .env")
    try:
        session = _create_threaded_resolver_session()
    except Exception:
        _logger.exception("Failed to create Telegram AiohttpSession with ThreadedResolver")
        return Bot(token=token, default=DefaultBotProperties(parse_mode=None))
    return Bot(token=token, session=session, default=DefaultBotProperties(parse_mode=None))


def create_telegram_application(
    config: AppConfig,
    template_catalog: TemplateCatalog,
    contract_engine: ContractEngine | None = None,
    schedule_tracker: Any = None,
    offers_service: Any = None,
) -> TelegramApplication:
    """Create Telegram bot and dispatcher without starting polling."""
    _validate_catalog(template_catalog)
    bot = create_bot(config)
    dispatcher = create_dispatcher(
        template_catalog=template_catalog,
        contract_engine=contract_engine,
        schedule_tracker=schedule_tracker,
        offers_service=offers_service,
        authorized_users=config.auth.authorized_users if hasattr(config, "auth") else None,
        unauthorized_action=config.auth.unauthorized_action if hasattr(config, "auth") else "ignore",
    )
    return TelegramApplication(bot=bot, dispatcher=dispatcher)


async def verify_telegram_connection(bot: Bot) -> None:
    """Verify that the bot token can authenticate with Telegram."""
    try:
        me = await bot.get_me()
    except Exception as error:
        _logger.exception(
            "Telegram authentication failed: type=%s repr=%r http_status=%s api_description=%s",
            type(error).__name__,
            error,
            _exception_http_status(error),
            _exception_api_description(error),
        )
        raise
    _logger.info("Telegram authentication OK: @%s", me.username)


async def run_polling(application: TelegramApplication) -> None:
    """Start Telegram long polling."""
    await verify_telegram_connection(application.bot)
    await setup_telegram_menu(application.bot)
    _logger.info("Telegram started")
    _logger.info("Polling started")
    await application.dispatcher.start_polling(application.bot)


async def setup_telegram_menu(bot: Bot) -> None:
    """Configure Telegram's command menu near the message input field."""
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать заново"),
            BotCommand(command="schedule", description="Расписание на сегодня"),
            BotCommand(command="offers", description="Поиск вакансий и ставок"),
            BotCommand(command="settings", description="Настройки мониторинга"),
        ]
    )
    _logger.info("Telegram command menu configured")


def _validate_catalog(template_catalog: TemplateCatalog) -> None:
    projects = template_catalog.list_projects()
    if not projects:
        raise TelegramStartupError("TemplateCatalog does not contain projects")
    _logger.info("Google Drive catalog loaded: %s projects", len(projects))


def _create_threaded_resolver_session() -> AiohttpSession:
    session = AiohttpSession()
    session._connector_init["resolver"] = ThreadedResolver()
    return session


def _exception_http_status(error: BaseException) -> object | None:
    status = getattr(error, "status", None)
    if status is not None:
        return status
    response = getattr(error, "response", None)
    return getattr(response, "status", None)


def _exception_api_description(error: BaseException) -> object | None:
    message = getattr(error, "message", None)
    if message is not None:
        return message
    return getattr(error, "description", None)
