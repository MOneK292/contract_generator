"""Google Sheets API client with client reuse, connection pooling, and exponential backoff retries."""

from __future__ import annotations

import asyncio
import logging
import random
import socket
import time
from typing import Any, Callable, TypeVar

from google.auth.exceptions import TransportError
from googleapiclient.errors import HttpError

_logger = logging.getLogger(__name__)

TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}
T = TypeVar("T")


class GoogleSheetsClient:
    """Non-blocking Google Sheets v4 API wrapper with persistent client and exponential backoff."""

    def __init__(
        self,
        google_auth: Any,
        max_retries: int = 3,
        base_backoff_seconds: float = 1.0,
    ) -> None:
        self.google_auth = google_auth
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._service = None

    def _get_service(self):
        """Get or lazily create the persistent Google Sheets API client."""
        if self._service is None:
            _logger.debug("Initializing Google Sheets API service client")
            self._service = self.google_auth.create_sheets_client()
        return self._service

    def reset_client(self) -> None:
        """Reset the cached service client to force re-authentication on next request."""
        self._service = None

    def _execute_with_retry(self, action_name: str, func: Callable[[], T]) -> T:
        """Execute a Google API function with exponential backoff for transient errors."""
        attempt = 0
        while True:
            try:
                return func()
            except HttpError as http_err:
                status_code = http_err.resp.status
                if status_code in TRANSIENT_HTTP_STATUS_CODES and attempt < self.max_retries:
                    attempt += 1
                    sleep_time = (self.base_backoff_seconds * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                    _logger.warning(
                        "Google API transient error %d during %s (attempt %d/%d). Retrying in %.2fs...",
                        status_code,
                        action_name,
                        attempt,
                        self.max_retries,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
                    continue
                _logger.error("Google API HttpError (%d) during %s: %s", status_code, action_name, http_err)
                raise
            except (TransportError, ConnectionError, socket.timeout, TimeoutError) as net_err:
                if attempt < self.max_retries:
                    attempt += 1
                    sleep_time = (self.base_backoff_seconds * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                    _logger.warning(
                        "Google API network/transport error during %s (attempt %d/%d): %s. Retrying in %.2fs...",
                        action_name,
                        attempt,
                        self.max_retries,
                        net_err,
                        sleep_time,
                    )
                    # Recreate service client on low-level connection breakdown
                    self.reset_client()
                    time.sleep(sleep_time)
                    continue
                _logger.error("Google API persistent network error during %s: %s", action_name, net_err)
                raise

    def _sync_get_sheet_names(self, spreadsheet_id: str) -> list[str]:
        def _call():
            service = self._get_service()
            metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheets = metadata.get("sheets", [])
            return [sheet.get("properties", {}).get("title", "") for sheet in sheets]

        return self._execute_with_retry(f"get_sheet_names({spreadsheet_id})", _call)

    def _sync_get_sheet_values(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        value_render_option: str = "FORMATTED_VALUE",
    ) -> list[list[Any]]:
        def _call():
            service = self._get_service()
            result = (
                service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=spreadsheet_id,
                    range=sheet_name,
                    valueRenderOption=value_render_option,
                )
                .execute()
            )
            return result.get("values", [])

        return self._execute_with_retry(
            f"get_sheet_values({spreadsheet_id}, {sheet_name})", _call
        )

    async def get_sheet_names(self, spreadsheet_id: str) -> list[str]:
        """Fetch all sheet titles asynchronously."""
        return await asyncio.to_thread(self._sync_get_sheet_names, spreadsheet_id)

    async def get_sheet_values(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        value_render_option: str = "FORMATTED_VALUE",
    ) -> list[list[Any]]:
        """Fetch cell values asynchronously."""
        return await asyncio.to_thread(
            self._sync_get_sheet_values,
            spreadsheet_id,
            sheet_name,
            value_render_option,
        )
