"""Telegram dispatcher factory."""

from __future__ import annotations

import logging

from typing import Any, Sequence

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from src.core.contract_engine import ContractEngine
from src.interfaces.telegram.handlers import register_handlers
from src.interfaces.telegram.middlewares import AuthorizationMiddleware
from src.interfaces.telegram.states import UserSessionStore
from src.services.config import TemplateCatalog

_logger = logging.getLogger(__name__)


def create_dispatcher(
    template_catalog: TemplateCatalog,
    contract_engine: ContractEngine | None = None,
    user_sessions: UserSessionStore | None = None,
    schedule_tracker: Any = None,
    offers_service: Any = None,
    authorized_users: Sequence[int] | None = None,
    unauthorized_action: str = "ignore",
) -> Dispatcher:
    """Create and configure the Telegram dispatcher with middleware and dependency injection."""
    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        template_catalog=template_catalog,
        contract_engine=contract_engine,
        user_sessions=user_sessions or UserSessionStore(),
        schedule_tracker=schedule_tracker,
        offers_service=offers_service,
    )

    if authorized_users:
        auth_middleware = AuthorizationMiddleware(
            authorized_users=authorized_users,
            unauthorized_action=unauthorized_action,
        )
        dispatcher.message.outer_middleware(auth_middleware)
        dispatcher.callback_query.outer_middleware(auth_middleware)
        _logger.info("AuthorizationMiddleware attached with %d allowed users", len(authorized_users))

    _logger.info("Dispatcher created")
    register_handlers(dispatcher)
    return dispatcher

