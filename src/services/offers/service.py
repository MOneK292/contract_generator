"""Central service orchestrator for Offers Engine."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional, Tuple

from src.services.offers.cache import OffersCache
from src.services.offers.catalog import OffersCatalog
from src.services.offers.loader import OffersLoader
from src.services.offers.models import CityOffers, OffersCatalogData
from src.services.offers.parser import OffersParser
from src.services.offers.validators import OffersValidator

_logger = logging.getLogger(__name__)


class OffersService:
    """Manages background sync, in-memory caching, and query operations for Offers Engine."""

    def __init__(
        self,
        google_auth: Any,
        sheet_id: str,
        poll_interval_seconds: int = 300,
        enabled: bool = True,
        samokat_sheet: str = "",
        lavka_sheet: str = "",
    ) -> None:
        self.google_auth = google_auth
        self.sheet_id = sheet_id
        self.poll_interval_seconds = poll_interval_seconds
        self.enabled = enabled
        self.samokat_sheet = samokat_sheet.strip()
        self.lavka_sheet = lavka_sheet.strip()

        self.loader = OffersLoader(google_auth, sheet_id)
        self.parser = OffersParser()
        self.validator = OffersValidator()

        self.catalog = OffersCatalog()
        self.cache = OffersCache(self.catalog)

        self._poll_task: Optional[asyncio.Task] = None
        self._running = False

    async def initialize(self) -> bool:
        """Perform initial catalog load into memory."""
        _logger.info("Initializing Offers Service with Sheet ID: %s", self.sheet_id)
        return await self.refresh_catalog()

    async def refresh_catalog(self) -> bool:
        """
        Fetch sheet data, parse, validate, and atomically swap catalog in memory per spec section 4.
        If fetch or parse fails, log error, preserve previous working catalog, and do not crash bot.
        """
        try:
            from src.services.offers.parser import LavkaParser
            
            sheets = await self.loader.get_sheet_names()
            if not sheets:
                raise ValueError("No sheets found")

            # Check explicit sheet configuration first
            samokat_sheet = self.samokat_sheet if (self.samokat_sheet and self.samokat_sheet in sheets) else None
            lavka_sheet = self.lavka_sheet if (self.lavka_sheet and self.lavka_sheet in sheets) else None

            # Fallback to intelligent pattern search if not configured
            if not samokat_sheet and not self.samokat_sheet:
                samokat_sheet = next((s for s in sheets if s == "Самокат "), None)
                if not samokat_sheet:
                    samokat_sheet = next((s for s in sheets if "самокат" in s.lower() and not any(x in s.lower() for x in ["сборщик", "кухн", "швеи"])), next((s for s in sheets if "sheet1" in s.lower() or "лист1" in s.lower() or "самокат" in s.lower()), None))
            if not lavka_sheet and not self.lavka_sheet:
                lavka_sheet = next((s for s in sheets if "лавка" in s.lower()), None)

            if not samokat_sheet and not lavka_sheet:
                if len(sheets) == 1:
                    samokat_sheet = sheets[0]
                else:
                    raise ValueError(f"No Samokat or Lavka sheets found in workbook: {sheets}")

            new_catalog = OffersCatalogData()
            all_parser_issues: List[str] = []

            if samokat_sheet:
                rows_samokat = await self.loader.fetch_rows(f"'{samokat_sheet}'!A1:Z500")
                catalog_samokat, samokat_issues = self.parser.parse(rows_samokat)
                all_parser_issues.extend(samokat_issues)
                new_catalog.cities.update(catalog_samokat.cities)

            if lavka_sheet:
                rows_lavka = await self.loader.fetch_rows(f"'{lavka_sheet}'!A1:Z500")
                lavka_parser = LavkaParser()
                catalog_lavka, lavka_issues = lavka_parser.parse(rows_lavka)
                all_parser_issues.extend(lavka_issues)

                # Merge catalogs
                for city_clean, city_offers in catalog_lavka.cities.items():
                    if city_clean in new_catalog.cities:
                        # Merge offers for existing city
                        new_catalog.cities[city_clean].offers.update(city_offers.offers)
                    else:
                        # Add new city
                        new_catalog.cities[city_clean] = city_offers

            new_catalog.rebuild_id_index()
            self.validator.validate(new_catalog, all_parser_issues)

            # Atomic swap
            self.catalog.set_catalog(new_catalog)
            _logger.info("Successfully refreshed Offers catalog (%d cities loaded)", len(new_catalog.cities))
            return True
        except Exception as error:
            _logger.exception("Failed to refresh Offers catalog from Google Sheet %s: %s", self.sheet_id, error)
            _logger.warning("Preserving previous working Offers catalog in memory per spec section 3")
            return False

    async def start_background_polling(self) -> None:
        """Start periodic background catalog polling loop."""
        if not self.enabled:
            _logger.info("Offers Service is disabled in configuration, skipping background polling")
            return

        if self._running:
            return

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        _logger.info("Started Offers Service background polling task (interval: %ds)", self.poll_interval_seconds)

    async def stop(self) -> None:
        """Stop background polling loop."""
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
            _logger.info("Stopped Offers Service background polling task")

    async def _poll_loop(self) -> None:
        """Periodic background polling loop."""
        while self._running:
            try:
                await asyncio.sleep(self.poll_interval_seconds)
                if self._running:
                    await self.refresh_catalog()
            except asyncio.CancelledError:
                break
            except Exception as error:
                _logger.exception("Unexpected error in Offers background poll loop: %s", error)

    def find_city(self, query_text: str) -> Tuple[Optional[CityOffers], List[CityOffers]]:
        """Search for city offers directly from in-memory cache without hitting Google API."""
        return self.cache.find_city(query_text)

    def find_city_by_id(self, city_id: str) -> Optional[CityOffers]:
        """Find city by its unique short identifier."""
        return self.catalog.get_city_by_id(city_id)
