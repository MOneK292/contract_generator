"""Background asyncio polling worker for schedule changes with locks, delivery guarantees, time windows, and Telegram retry handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter

from src.services.schedule_tracker.message_formatter import format_schedule_message
from src.services.schedule_tracker.models import ScheduleReport
from src.services.schedule_tracker.time_utils import is_within_time_window
from src.services.schedule_tracker.tracker_service import ScheduleTrackerService

_logger = logging.getLogger(__name__)


class SchedulePoller:
    """Runs background polling loop checking Google Sheets every N seconds with zero concurrency overlap and delivery confirmation."""

    def __init__(
        self,
        bot: Bot,
        tracker: ScheduleTrackerService,
        recipients: Sequence[int | str] | int | str,
        interval_seconds: int = 60,
        enabled: bool = True,
        notification_start_time: str = "09:00",
        notification_end_time: str = "20:00",
        max_telegram_retries: int = 3,
    ) -> None:
        self.bot = bot
        self.tracker = tracker
        if isinstance(recipients, (int, str)):
            self.recipients = [recipients]
        else:
            self.recipients = list(recipients)
        self.default_interval_seconds = max(5, interval_seconds)
        self.default_enabled = enabled
        self.default_notification_start_time = notification_start_time
        self.default_notification_end_time = notification_end_time
        self.max_telegram_retries = max_telegram_retries

        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._running: bool = False

    async def _send_notification_to_recipient(self, text: str, recipient: int | str) -> bool:
        """Send notification to a specific recipient with rate-limit and transient error handling."""
        attempt = 0
        while attempt < self.max_telegram_retries:
            attempt += 1
            try:
                await self.bot.send_message(
                    chat_id=recipient,
                    text=text,
                    parse_mode="HTML",
                )
                return True
            except TelegramRetryAfter as retry_err:
                _logger.warning(
                    "Telegram rate limited for recipient %s. Waiting %d seconds before retry...",
                    recipient,
                    retry_err.retry_after,
                )
                await asyncio.sleep(retry_err.retry_after + 1)
                continue
            except (TelegramNetworkError, TelegramAPIError, ConnectionError, asyncio.TimeoutError) as tg_err:
                _logger.warning(
                    "Telegram delivery to %s attempt %d/%d failed: %s",
                    recipient,
                    attempt,
                    self.max_telegram_retries,
                    tg_err,
                )
                if attempt < self.max_telegram_retries:
                    await asyncio.sleep(2.0 * attempt)
                    continue
                _logger.error(
                    "Failed to deliver schedule notification to Telegram recipient %s after %d attempts",
                    recipient,
                    self.max_telegram_retries,
                )
                return False
            except Exception as unk_err:
                _logger.exception("Unexpected error while sending Telegram message to %s: %s", recipient, unk_err)
                return False

        return False

    async def _broadcast_notification(self, text: str) -> bool:
        """Broadcast message to all configured recipients based on their individual user settings. Returns True if at least one was delivered or if state commit is safe."""
        if not self.recipients:
            _logger.warning("No recipients configured for schedule notifications.")
            return False

        delivered_any = False
        repo = getattr(self.tracker, "repository", None)

        for recipient in self.recipients:
            user_id = None
            try:
                user_id = int(recipient)
            except (ValueError, TypeError):
                pass

            if repo and user_id and hasattr(repo, "get_user_settings"):
                user_settings = await repo.get_user_settings(user_id)
                if not user_settings.get("enabled", True):
                    _logger.debug("Notifications disabled for recipient %s", recipient)
                    continue

                start_time = user_settings.get("notification_start_time", self.default_notification_start_time)
                end_time = user_settings.get("notification_end_time", self.default_notification_end_time)

                if not is_within_time_window(
                    start_time_str=start_time,
                    end_time_str=end_time,
                    tz_name=self.tracker.timezone,
                ):
                    _logger.debug(
                        "Recipient %s current time outside user window (%s - %s MSK). Skipping notification.",
                        recipient,
                        start_time,
                        end_time,
                    )
                    continue

            success = await self._send_notification_to_recipient(text, recipient)
            if success:
                delivered_any = True

        return delivered_any

    async def _poll_iteration(self) -> None:
        """Execute a single polling iteration protected by asyncio.Lock."""
        if self._lock.locked():
            _logger.warning("Previous schedule monitoring cycle still running, skipping overlap")
            return

        repo = getattr(self.tracker, "repository", None)
        if repo and hasattr(repo, "get_settings"):
            settings = await repo.get_settings()
            is_enabled = bool(settings.get("enabled", self.default_enabled))
            if not is_enabled:
                return

        async with self._lock:
            report: ScheduleReport | None = await self.tracker.check_for_updates()
            if report:
                text = format_schedule_message(report)
                sent = await self._broadcast_notification(text)
                if sent:
                    # ONLY commit state once message was confirmed sent!
                    await self.tracker.commit_report(report)
                    _logger.info(
                        "Schedule update delivered to recipients and committed for %s (%d diffs)",
                        self.tracker.manager_name,
                        len(report.diffs),
                    )
                else:
                    _logger.warning(
                        "Notification delivery failed; state was NOT committed and will retry on next poll cycle"
                    )

    async def start(self) -> None:
        """Start the background polling loop."""
        settings = await self.tracker.repository.get_settings()
        interval = settings.get("poll_interval_seconds") or self.default_interval_seconds
        start_time = settings.get("notification_start_time") or self.default_notification_start_time
        end_time = settings.get("notification_end_time") or self.default_notification_end_time

        self._running = True
        _logger.info(
            "Starting schedule poller (interval: %ds, recipients: %s, window: %s-%s MSK, manager: %s)",
            interval,
            self.recipients,
            start_time,
            end_time,
            self.tracker.manager_name,
        )

        while self._running:
            try:
                await self._poll_iteration()
            except asyncio.CancelledError:
                _logger.info("Schedule poller cancelled.")
                break
            except Exception as error:
                _logger.exception("Error in schedule poller loop: %s", error)

            try:
                settings = await self.tracker.repository.get_settings()
                current_interval = settings.get("poll_interval_seconds") or self.default_interval_seconds
                await asyncio.sleep(current_interval)
            except asyncio.CancelledError:
                break

    def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
