"""Dynamic table structure parser for Offers Engine."""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from src.services.offers.models import CityOffers, JobType, Offer, OffersCatalogData

_logger = logging.getLogger(__name__)


class HeaderNotFoundError(Exception):
    """Raised when mandatory header columns are missing."""


class OffersParser:
    """Parses raw Google Sheets rows into structured OffersCatalogData based on header names."""

    CITY_KEYWORDS = ["город", "населенный пункт", "сити", "локация"]
    JOB_TYPE_KEYWORDS = ["тип вакансии", "должность", "тип работы", "вакансия", "вид курьера", "направление", "роль", "тип", "профессия", "операция"]
    LEGAL_ENTITY_KEYWORDS = ["юрлицо", "юр. лицо", "юр.лицо", "юр лицо", "юридическое лицо", "организация", "компания", "работодатель", "юр", "юл"]

    RATE_1_KEYWORDS = [
        "ставка за час",
        "цена для персонала",
        "тариф руб/час",
        "тариф руб",
        "оплата за час",
        "почасовая ставка",
        "ставка 1",
        "тариф 1",
        "ставка",
        "гарантированный доход",
    ]
    RATE_2_KEYWORDS = [
        "оплата за стоп sla 15",
        "sla 15",
        "sla15",
        "за заказ",
        "доплата за заказ",
        "сдельная ставка",
        "ставка 2",
        "тариф 2",
    ]
    RATE_3_KEYWORDS = [
        "оплата за стоп  sla 30 и более",
        "оплата за стоп sla 30",
        "sla 30",
        "sla30",
        "в смену 12 часов",
        "ставка 3",
        "тариф 3",
    ]

    def __init__(self, project_name: str = "Самокат"):
        self.project_name = project_name

    def parse(self, rows: List[List[str]]) -> Tuple[OffersCatalogData, List[str]]:
        """Parse 2D list of row strings into an OffersCatalogData instance and a list of parsing issues."""
        if not rows:
            raise HeaderNotFoundError("Sheet data is empty")

        # Locate header row within first 5 rows
        header_row_idx = 0
        for i, row in enumerate(rows[:5]):
            row_lower = [c.strip().lower() for c in row]
            if any(any(k in c for k in self.JOB_TYPE_KEYWORDS) for c in row_lower):
                header_row_idx = i
                break

        header_row = [cell.strip().lower() for cell in rows[header_row_idx]]
        col_map = self._build_column_map(header_row)

        # Fallback for legal entity from top banners if not in columns
        top_banner_legal = ""
        if col_map.get("legal_entity", -1) == -1:
            for r in rows[:header_row_idx + 1]:
                for cell in r:
                    if "юл" in cell.lower() or "ооо" in cell.lower():
                        top_banner_legal = cell.strip()
                        break
                if top_banner_legal:
                    break

        cities_map: Dict[str, CityOffers] = {}
        issues: List[str] = []

        current_city = ""
        current_legal = ""

        for row_idx, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
            if not row or not any(cell.strip() for cell in row):
                continue

            city_cell = self._get_cell(row, col_map.get("city", -1))
            if city_cell:
                current_city = city_cell

            city_raw = current_city
            job_type_raw = self._get_cell(row, col_map.get("job_type", -1))
            legal_cell = self._get_cell(row, col_map.get("legal_entity", -1))
            if legal_cell:
                current_legal = legal_cell

            legal_entity = current_legal or top_banner_legal or ("ООО Самокат" if self.project_name == "Самокат" else "ООО Яндекс Лавка")
            rate_1 = self._get_cell(row, col_map.get("rate_1", -1))
            rate_2 = self._get_cell(row, col_map.get("rate_2", -1))
            rate_3 = self._get_cell(row, col_map.get("rate_3", -1))

            if not city_raw or not job_type_raw:
                continue

            # Skip header repeats or priority notes
            if "приоритет" in job_type_raw.lower():
                continue

            job_type = JobType.normalize(job_type_raw)
            if job_type is None:
                # Ignored job type per spec
                continue

            # Check if multiple cities are listed in the row
            cities_to_apply: List[Tuple[str, str]] = []
            if any(sep in city_raw for sep in [",", ";", "\n"]):
                cities_to_apply = self._extract_cities_from_text(city_raw)
            
            # Also check last columns (bonus/info notes) for bulk cities in Samokat
            if not cities_to_apply:
                for last_col_idx in range(len(row) - 1, max(col_map.values()), -1):
                    val = self._get_cell(row, last_col_idx)
                    if val and ("," in val or "\n" in val):
                        extracted = self._extract_cities_from_text(val)
                        if len(extracted) > 1:
                            cities_to_apply = extracted
                            break

            if not cities_to_apply:
                city_clean = self.clean_city_name(city_raw)
                if city_clean:
                    cities_to_apply = [(city_clean, city_raw.strip())]

            for city_clean, city_full in cities_to_apply:
                if not city_clean:
                    continue

                if city_clean not in cities_map:
                    cities_map[city_clean] = CityOffers(city_full=city_full, city_clean=city_clean)

                city_entry = cities_map[city_clean]

                offer = Offer(
                    city_full=city_full,
                    city_clean=city_clean,
                    job_type=job_type,
                    legal_entity=legal_entity,
                    rate_1=rate_1,
                    rate_2=rate_2,
                    rate_3=rate_3,
                    project=self.project_name,
                )

                if job_type in city_entry.offers:
                    issues.append(f"Row {row_idx}: Duplicate job type '{job_type.value}' for city '{city_full}'")
                else:
                    city_entry.offers[job_type] = offer

        return OffersCatalogData(cities=cities_map), issues

    CITY_ALIASES = {
        "спб": "санкт-петербург",
        "питер": "санкт-петербург",
        "петербург": "санкт-петербург",
        "с-петербург": "санкт-петербург",
        "мск": "москва",
        "екб": "екатеринбург",
        "нн": "нижний новгород",
        "н.новгород": "нижний новгород",
        "рнд": "ростов-на-дону",
    }

    @classmethod
    def clean_city_name(cls, city_raw: str) -> str:
        """Strip text inside parentheses, normalize dashes/spaces, and map common aliases."""
        cleaned = re.sub(r"\(.*?\)", "", city_raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
        cleaned = re.sub(r"\s*-\s*", "-", cleaned)
        return cls.CITY_ALIASES.get(cleaned, cleaned)

    def _extract_cities_from_text(self, text: str) -> List[Tuple[str, str]]:
        result: List[Tuple[str, str]] = []
        parts = re.split(r'[,;\n]+', text)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            clean = self.clean_city_name(part)
            clean = clean.replace("только", "").replace("рф", "").replace("патентом", "").replace("не оформляем", "").strip()
            if clean and len(clean) >= 2 and clean not in ["мск", "для", "открытия", "пеший", "вело", "условия", "депозит", "сотрудников"]:
                disp = "-".join(p.capitalize() for p in clean.split("-"))
                result.append((clean, disp))
        seen = set()
        dedup = []
        for c, d in result:
            if c not in seen:
                seen.add(c)
                dedup.append((c, d))
        return dedup

    def _build_column_map(self, header_row: List[str]) -> Dict[str, int]:
        """Dynamically locate column indices by header titles per spec section 3."""
        col_map: Dict[str, int] = {}

        col_map["city"] = self._find_column(header_row, self.CITY_KEYWORDS, "Город", required=True)
        col_map["job_type"] = self._find_column(header_row, self.JOB_TYPE_KEYWORDS, "Тип работы", required=True)
        col_map["legal_entity"] = self._find_column(header_row, self.LEGAL_ENTITY_KEYWORDS, "Юрлицо", required=False)

        col_map["rate_1"] = self._find_column(header_row, self.RATE_1_KEYWORDS, "Ставка 1", required=self.project_name == "Самокат")
        col_map["rate_2"] = self._find_column(header_row, self.RATE_2_KEYWORDS, "Ставка 2", required=False)
        col_map["rate_3"] = self._find_column(header_row, self.RATE_3_KEYWORDS, "Ставка 3", required=False)

        _logger.debug("Offers column map built: %s", col_map)
        return col_map

    def _find_column(self, header_row: List[str], keywords: List[str], field_name: str, required: bool = True) -> int:
        for keyword in keywords:
            keyword_clean = keyword.lower().replace(".", "").replace(" ", "")
            for idx, col_title in enumerate(header_row):
                col_clean = col_title.lower().replace(".", "").replace(" ", "")
                if keyword in col_title.lower() or (len(keyword_clean) >= 3 and keyword_clean in col_clean):
                    return idx
        if field_name == "Город" and len(header_row) > 0 and header_row[0].strip().lower() == "а":
            return 0
        if required:
            raise HeaderNotFoundError(f"Required header column '{field_name}' not found in Google Sheet")
        return -1

    def _get_cell(self, row: List[str], col_idx: int) -> str:
        if 0 <= col_idx < len(row):
            return row[col_idx].strip()
        return ""


class LavkaParser(OffersParser):
    def __init__(self):
        super().__init__(project_name="Яндекс Лавка")
