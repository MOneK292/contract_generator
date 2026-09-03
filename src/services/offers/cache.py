"""Zero-latency in-memory query cache for Offers Engine."""

from __future__ import annotations

import difflib
from typing import List, Optional, Tuple

from src.services.offers.catalog import OffersCatalog
from src.services.offers.models import CityOffers
from src.services.offers.parser import OffersParser


class OffersCache:
    """Fast in-memory query engine operating exclusively on in-memory catalog data."""

    def __init__(self, catalog: OffersCatalog) -> None:
        self.catalog = catalog

    def find_city(self, query_text: str) -> Tuple[Optional[CityOffers], List[CityOffers]]:
        """
        Search for a city by query text per spec section 7:
        1. Exact match (cleaned text without parentheses).
        2. If not found, return up to 5 similar city suggestions.
        """
        clean_query = OffersParser.clean_city_name(query_text)
        if not clean_query:
            return None, []

        all_cities = self.catalog.list_cities()

        # 1. Exact match
        for city in all_cities:
            if city.city_clean == clean_query:
                return city, []

        # 2. Substring match or difflib suggestions
        substring_matches = [
            c for c in all_cities if clean_query in c.city_clean or c.city_clean in clean_query
        ]
        if substring_matches:
            return None, substring_matches[:5]

        # Fuzzy match using difflib
        city_names = [c.city_clean for c in all_cities]
        close_names = difflib.get_close_matches(clean_query, city_names, n=5, cutoff=0.5)

        suggestions = [c for c in all_cities if c.city_clean in close_names]
        return None, suggestions
