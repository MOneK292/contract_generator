"""Google Sheets data loader for Offers Engine."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

_logger = logging.getLogger(__name__)


class OffersLoaderError(Exception):
    """Raised when loading offers from Google Sheets fails."""


class OffersLoader:
    """Non-blocking Google Sheets fetcher for vacancy and offer data."""

    def __init__(self, google_auth: Any, sheet_id: str) -> None:
        self.google_auth = google_auth
        self.sheet_id = sheet_id
        self._service = None

    def _get_service(self):
        """Get or lazily create the persistent Google Sheets API client."""
        if self._service is None:
            self._service = self.google_auth.create_sheets_client()
        return self._service

    def reset_client(self) -> None:
        """Reset cached client on connection failure."""
        self._service = None

    def _sync_fetch_sheet_data(self, range_name: Optional[str] = None) -> List[List[str]]:
        """Fetch rows from Google Sheets synchronously."""
        try:
            sheets_client = self._get_service()
            
            # If range_name is not provided, fetch the first sheet's name
            if not range_name:
                spreadsheet_metadata = (
                    sheets_client.spreadsheets()
                    .get(spreadsheetId=self.sheet_id)
                    .execute()
                )
                sheets = spreadsheet_metadata.get("sheets", [])
                if not sheets:
                    raise OffersLoaderError(f"No sheets found in spreadsheet {self.sheet_id}")
                range_name = f"'{sheets[0]['properties']['title']}'!A1:Z500"

            result = (
                sheets_client.spreadsheets()
                .values()
                .get(spreadsheetId=self.sheet_id, range=range_name)
                .execute()
            )
            rows = result.get("values", [])
            _logger.info("Loaded %d rows from Google Sheet %s (range: %s)", len(rows), self.sheet_id, range_name)
            return rows
        except Exception as error:
            self.reset_client()
            _logger.exception("Failed to load offers from Google Sheet %s: %s", self.sheet_id, error)
            raise OffersLoaderError(f"Failed to fetch sheet data: {error}") from error

    def _sync_get_sheet_names(self) -> List[str]:
        try:
            sheets_client = self._get_service()
            spreadsheet_metadata = (
                sheets_client.spreadsheets()
                .get(spreadsheetId=self.sheet_id)
                .execute()
            )
            sheets = spreadsheet_metadata.get("sheets", [])
            return [s["properties"]["title"] for s in sheets]
        except Exception as error:
            self.reset_client()
            _logger.exception("Failed to load sheet names from Google Sheet %s: %s", self.sheet_id, error)
            raise OffersLoaderError(f"Failed to fetch sheet names: {error}") from error

    async def get_sheet_names(self) -> List[str]:
        return await asyncio.to_thread(self._sync_get_sheet_names)

    async def fetch_rows(self, range_name: Optional[str] = None) -> List[List[str]]:
        """Fetch rows from Google Sheets asynchronously."""
        return await asyncio.to_thread(self._sync_fetch_sheet_data, range_name)
