"""Telegram handlers registration."""

from __future__ import annotations

import logging

from aiogram import Dispatcher

from src.interfaces.telegram.handlers import employee, project, schedule, start, template, vacancy

_logger = logging.getLogger(__name__)


def register_handlers(dispatcher: Dispatcher) -> None:
    """Register all Telegram routers in the dispatcher."""
    dispatcher.include_router(start.router)
    
    try:
        from src.interfaces.telegram.handlers import settings
        dispatcher.include_router(settings.settings_router)
    except ImportError as e:
        _logger.warning("Settings handler not loaded: %s", e)

    dispatcher.include_router(schedule.router)
    dispatcher.include_router(project.router)
    dispatcher.include_router(vacancy.router)
    dispatcher.include_router(template.router)
    
    try:
        from src.interfaces.telegram.handlers import crm_lookup
        dispatcher.include_router(crm_lookup.router)
        _logger.info("CRM lookup handler registered")
    except ImportError:
        _logger.warning("CRM lookup handler not found")

    dispatcher.include_router(employee.router)

    try:
        from src.interfaces.telegram.handlers.offers import offers_router
        dispatcher.include_router(offers_router)
        _logger.info("Offers router registered")
    except ImportError as e:
        _logger.warning("Offers router not loaded: %s", e)

    _logger.info("Handlers registered")


__all__ = ["register_handlers"]
