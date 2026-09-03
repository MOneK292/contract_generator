"""Telegram middlewares package."""

from src.interfaces.telegram.middlewares.auth import AuthorizationMiddleware

__all__ = ["AuthorizationMiddleware"]
