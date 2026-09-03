"""In-memory catalog container for Offers Engine."""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from src.services.offers.models import CityOffers, OffersCatalogData

_logger = logging.getLogger(__name__)


class OffersCatalog:
    """Thread-safe in-memory catalog with atomic swap capability."""

    def __init__(self, catalog_data: Optional[OffersCatalogData] = None) -> None:
        self._lock = threading.RLock()
        self._data: OffersCatalogData = catalog_data or OffersCatalogData()

    def get_catalog(self) -> OffersCatalogData:
        """Get the current atomic snapshot of the catalog data."""
        with self._lock:
            return self._data

    def set_catalog(self, new_data: OffersCatalogData) -> None:
        """Atomically replace the internal catalog snapshot."""
        with self._lock:
            old_count = len(self._data.cities)
            self._data = new_data
            new_count = len(new_data.cities)
            _logger.info("Offers catalog atomically updated in memory (%d -> %d cities)", old_count, new_count)

    def get_city(self, city_clean: str) -> Optional[CityOffers]:
        """Look up city offers by clean city name."""
        with self._lock:
            return self._data.get_city(city_clean)

    def get_city_by_id(self, city_id: str) -> Optional[CityOffers]:
        """Look up city offers by unique short city ID."""
        with self._lock:
            return self._data.get_city_by_id(city_id)

    def list_cities(self) -> List[CityOffers]:
        """List all city offers in current catalog snapshot."""
        with self._lock:
            return list(self._data.cities.values())
