"""Domain data models for the Offers Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ProjectType(str, Enum):
    SAMOKAT = "Самокат"
    LAVKA = "Яндекс Лавка"

class JobType(str, Enum):
    """Supported job offer types."""
    VELO = "Вело-курьер"
    ELECTRO = "Электро-велокурьер"
    VAHTA = "Вахта"
    LAVKA_PICKER = "Сборщик"
    LAVKA_COOK = "Повар"

    @classmethod
    def normalize(cls, text: str) -> Optional[JobType]:
        """Normalize job type string into standard JobType enum or None if ignored/unknown."""
        raw = text.strip().lower()
        
        # Ignored markers per spec section 5
        if "(приоритет)" in raw or "(базовые цфз)" in raw:
            return None
            
        if "электро" in raw:
            return cls.ELECTRO
        if "вело" in raw:
            return cls.VELO
        if "вахта" in raw:
            return cls.VAHTA
        if "сборщик" in raw:
            return cls.LAVKA_PICKER
        if "повар" in raw:
            return cls.LAVKA_COOK
            
        return None


@dataclass(frozen=True)
class Offer:
    """Individual job offer detailing city, type, legal entity, and rates."""

    city_full: str
    city_clean: str
    job_type: JobType
    legal_entity: str
    rate_1: str
    rate_2: str
    rate_3: str
    project: str = ProjectType.SAMOKAT.value


import hashlib


def generate_city_id(city_clean: str) -> str:
    """Generate a deterministic collision-free short ID string (12 hex chars) from clean city name."""
    return hashlib.blake2s(city_clean.strip().lower().encode("utf-8"), digest_size=6).hexdigest()


@dataclass
class CityOffers:
    """Offers grouped for a specific city."""

    city_full: str
    city_clean: str
    offers: Dict[JobType, Offer] = field(default_factory=dict)
    city_id: str = ""

    def __post_init__(self) -> None:
        if not self.city_id and self.city_clean:
            self.city_id = generate_city_id(self.city_clean)


@dataclass
class OffersCatalogData:
    """Complete in-memory snapshot of all city offers."""

    cities: Dict[str, CityOffers] = field(default_factory=dict)
    by_id: Dict[str, CityOffers] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rebuild_id_index()

    def rebuild_id_index(self) -> None:
        """Build O(1) index mapping city_id to CityOffers."""
        self.by_id = {}
        for city_clean, city_offers in self.cities.items():
            if not city_offers.city_id:
                city_offers.city_id = generate_city_id(city_clean)
            self.by_id[city_offers.city_id] = city_offers

    def get_city(self, city_clean: str) -> Optional[CityOffers]:
        """Get city offers by clean city name."""
        return self.cities.get(city_clean.lower().strip())

    def get_city_by_id(self, city_id: str) -> Optional[CityOffers]:
        """Get city offers by unique short city ID."""
        return self.by_id.get(str(city_id).strip())
