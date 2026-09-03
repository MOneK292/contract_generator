"""Employee text parser."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field


@dataclass
class EmployeeParser:
    """Parses user text into raw employee fields without computed values."""

    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def parse(self, text: str) -> dict[str, str]:
        """Parse raw HR text into a dictionary of unchanged fields."""
        result: dict[str, str] = {}

        for line_number, line in enumerate(text.splitlines(), start=1):
            parsed_fields = self._parse_line(line)
            if not parsed_fields:
                self._logger.debug("Skipping unrecognized line: %s", line_number)
                continue

            for key, value in parsed_fields:
                if key == "" or value == "":
                    self._logger.debug("Skipping line with empty field name: %s", line_number)
                    continue

                result[key] = value

        self._logger.debug("Parsed employee fields: %s", len(result))
        return result

    def _parse_line(self, line: str) -> tuple[tuple[str, str], ...]:
        stripped = line.strip()
        if not stripped:
            return ()

        field = self._parse_delimited_field(stripped)
        if field is not None:
            return (field,)

        field = self._parse_known_space_field(stripped)
        if field is not None:
            return (field,)

        return self._parse_free_form_identity(stripped)

    def _parse_delimited_field(self, line: str) -> tuple[str, str] | None:
        match = re.match(r"^\s*(?P<key>.+?)\s*(?::|—|=|\s-\s)\s*(?P<value>.+?)\s*$", line)
        if match is None:
            return None
        key = self._canonical_key(match.group("key"))
        return key, match.group("value").strip()

    def _parse_known_space_field(self, line: str) -> tuple[str, str] | None:
        normalized_line = self._normalize_key(line)
        aliases = sorted(
            self._aliases().items(),
            key=lambda item: len(item[0].split()),
            reverse=True,
        )
        for alias, canonical in aliases:
            if normalized_line == alias:
                return None
            prefix = f"{alias} "
            if normalized_line.startswith(prefix):
                value = line[len(self._matching_prefix(line, alias)) :].strip()
                if value:
                    return canonical, value
        return None

    def _parse_free_form_identity(self, line: str) -> tuple[tuple[str, str], ...]:
        phone = self._extract_phone(line)
        fio = self._extract_fio(line, phone)
        if fio and phone:
            return (("ФИО", fio), ("Телефон", phone))
        if phone and self._normalize_phone(line) == phone:
            return (("Телефон", phone),)
        if fio:
            return (("ФИО", fio),)
        return ()

    def _canonical_key(self, key: str) -> str:
        return self._aliases().get(self._normalize_key(key), key.strip())

    def _normalize_key(self, key: str) -> str:
        normalized = key.strip().casefold().replace("ё", "е")
        normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
        return re.sub(r"\s+", " ", normalized).strip()

    def _matching_prefix(self, line: str, normalized_alias: str) -> str:
        words = normalized_alias.split()
        original_words = line.strip().split()
        return " ".join(original_words[: len(words)])

    def _extract_phone(self, line: str) -> str | None:
        match = re.search(r"(?:\+7|7|8)\D*\d{3}\D*\d{3}\D*\d{2}\D*\d{2}", line)
        if match is None:
            return None
        return self._normalize_phone(match.group(0))

    def _normalize_phone(self, value: str) -> str:
        digits = re.sub(r"\D+", "", value)
        if len(digits) == 11 and digits.startswith("8"):
            return "7" + digits[1:]
        return digits

    def _extract_fio(self, line: str, phone: str | None) -> str | None:
        candidate = line
        if phone:
            candidate = re.sub(r"(?:\+7|7|8)\D*\d{3}\D*\d{3}\D*\d{2}\D*\d{2}", "", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if re.fullmatch(r"[А-Яа-яЁё]+(?:[- ][А-Яа-яЁё]+){1,3}", candidate):
            return candidate
        return None

    def _aliases(self) -> dict[str, str]:
        return {
            "фио": "ФИО",
            "инн": "ИНН",
            "снилс": "СНИЛС",
            "телефон": "Телефон",
            "номер": "Номер",
            "почта": "Почта",
            "email": "Почта",
            "e mail": "Почта",
            "дата рождения": "Дата рождения",
            "серия номер п": "Серия, номер П",
            "паспорт": "Серия, номер П",
            "паспорт рф": "Серия, номер П",
            "серия паспорта": "Серия, номер П",
            "номер паспорта": "Серия, номер П",
            "кем выдан": "Кем выдан",
            "выдан": "Кем выдан",
            "выдан кем": "Кем выдан",
            "регистрация": "Регистрация",
            "дата выдачи": "Дата выдачи",
        }
