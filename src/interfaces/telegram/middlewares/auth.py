"""Telegram authorization middleware filtering unauthorized users by whitelist."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

_logger = logging.getLogger(__name__)


class AuthorizationMiddleware(BaseMiddleware):
    """Restricts access to bot features to a configured whitelist of Telegram user IDs."""

    def __init__(
        self,
        authorized_users: tuple[int, ...] | list[int] | set[int],
        unauthorized_action: str = "ignore",
    ) -> None:
        super().__init__()
        self.authorized_users = set(authorized_users)
        self.unauthorized_action = unauthorized_action.strip().lower()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = data.get("event_from_user") or getattr(event, "from_user", None)

        if from_user is None:
            return await handler(event, data)

        if from_user.id in self.authorized_users:
            return await handler(event, data)

        _logger.warning(
            "Access denied for unauthorized user ID=%s (@%s)",
            from_user.id,
            from_user.username or "no_username",
        )

        if self.unauthorized_action == "reply":
            if isinstance(event, Message):
                try:
                    await event.answer("⛔ У вас нет доступа к функциям этого бота.")
                except Exception:
                    pass
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer("⛔ Доступ ограничен.", show_alert=True)
                except Exception:
                    pass

        return None
