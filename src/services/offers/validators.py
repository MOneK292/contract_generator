"""Validation and auditing module for Offers Engine."""

from __future__ import annotations

import logging
from typing import List

from src.services.offers.models import OffersCatalogData

_logger = logging.getLogger(__name__)


class OffersValidator:
    """Validates catalog integrity and logs anomalies per spec section 11."""

    def validate(self, catalog: OffersCatalogData, parser_issues: List[str]) -> bool:
        """Validate catalog contents and record issues to server log."""
        all_warnings: List[str] = list(parser_issues)

        for city_clean, city_offers in catalog.cities.items():
            if not city_offers.offers:
                all_warnings.append(f"City '{city_offers.city_full}' has no active offers")
                continue

            for job_type, offer in city_offers.offers.items():
                if not offer.legal_entity:
                    all_warnings.append(
                        f"Offer '{job_type.value}' in city '{city_offers.city_full}' is missing Legal Entity"
                    )
                if offer.project == "Яндекс Лавка":
                    if not offer.rate_1:
                        all_warnings.append(
                            f"Offer '{job_type.value}' ({offer.project}) in city '{city_offers.city_full}' is missing Rate1"
                        )
                else:
                    if not offer.rate_1 or not offer.rate_2 or not offer.rate_3:
                        all_warnings.append(
                            f"Offer '{job_type.value}' ({offer.project}) in city '{city_offers.city_full}' has incomplete rates "
                            f"(Rate1='{offer.rate_1}', Rate2='{offer.rate_2}', Rate3='{offer.rate_3}')"
                        )

        if all_warnings:
            _logger.warning("Offers catalog validation completed with %d warnings:", len(all_warnings))
            for warning in all_warnings:
                _logger.warning("  - %s", warning)
            return False

        _logger.info("Offers catalog validation passed cleanly with %d cities", len(catalog.cities))
        return True
