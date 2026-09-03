"""Money-derived fields processor."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from src.processors.base import FieldProcessor


@dataclass
class MoneyProcessor(FieldProcessor):
    """Normalizes money fields and adds their text representation."""

    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def process(self, data: dict[str, str]) -> dict[str, str]:
        """Normalize detected money fields and add `<field> Прописью` values."""
        result = dict(data)

        for field_name, field_value in data.items():
            if not self._is_money_field(field_name):
                continue

            amount = self._parse_amount(field_value)
            if amount is None:
                self._logger.debug("Skipping invalid money field: %s", field_name)
                continue

            normalized = self._format_amount(amount)
            words = self._amount_to_words(amount)
            result[field_name] = f"{normalized} ({words})"
            result[f"{field_name} Прописью"] = words

        return result

    def _is_money_field(self, field_name: str) -> bool:
        normalized = field_name.lower()
        if normalized.endswith("прописью"):
            return False

        keywords = ("ставка", "плата", "стоимость", "сумма", "оплата")
        return any(keyword in normalized for keyword in keywords)

    def _parse_amount(self, value: str) -> Decimal | None:
        normalized = self._normalize_decimal_separator(value)
        try:
            return Decimal(normalized).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return None

    def _normalize_decimal_separator(self, value: str) -> str:
        normalized = value.strip().replace(" ", "").replace("\u00a0", "")
        if "," in normalized and "." in normalized:
            comma_position = normalized.rfind(",")
            dot_position = normalized.rfind(".")
            if comma_position > dot_position:
                normalized = normalized.replace(".", "").replace(",", ".")
            else:
                normalized = normalized.replace(",", "")
            return normalized

        return normalized.replace(",", ".")

    def _format_amount(self, amount: Decimal) -> str:
        return format(amount, ".2f").replace(".", ",")

    def _amount_to_words(self, amount: Decimal) -> str:
        rubles = int(amount)
        kopecks = int((amount - Decimal(rubles)) * 100)
        ruble_words = self._integer_to_words(rubles, "masculine")
        ruble_unit = self._plural_form(rubles, "рубль", "рубля", "рублей")
        
        kopeck_words = self._integer_to_words(kopecks, "feminine")
        kopeck_unit = self._plural_form(kopecks, "копейка", "копейки", "копеек")
        return f"{ruble_words} {ruble_unit}, {kopeck_words} {kopeck_unit}"

    def _integer_to_words(self, number: int, gender: str = "masculine") -> str:
        if number == 0:
            return "ноль"

        groups = (
            ("", "", "", gender),
            ("тысяча", "тысячи", "тысяч", "feminine"),
            ("миллион", "миллиона", "миллионов", "masculine"),
            ("миллиард", "миллиарда", "миллиардов", "masculine"),
        )
        words: list[str] = []
        group_index = 0

        while number > 0:
            triplet = number % 1000
            if triplet:
                group = groups[group_index]
                triplet_words = self._triplet_to_words(triplet, group[3])
                scale_word = self._plural_form(triplet, group[0], group[1], group[2])
                if scale_word:
                    triplet_words.append(scale_word)
                words = triplet_words + words
            number //= 1000
            group_index += 1

        return " ".join(words)

    def _triplet_to_words(self, number: int, gender: str) -> list[str]:
        hundreds = (
            "",
            "сто",
            "двести",
            "триста",
            "четыреста",
            "пятьсот",
            "шестьсот",
            "семьсот",
            "восемьсот",
            "девятьсот",
        )
        tens = (
            "",
            "",
            "двадцать",
            "тридцать",
            "сорок",
            "пятьдесят",
            "шестьдесят",
            "семьдесят",
            "восемьдесят",
            "девяносто",
        )
        teens = (
            "десять",
            "одиннадцать",
            "двенадцать",
            "тринадцать",
            "четырнадцать",
            "пятнадцать",
            "шестнадцать",
            "семнадцать",
            "восемнадцать",
            "девятнадцать",
        )
        masculine_units = (
            "",
            "один",
            "два",
            "три",
            "четыре",
            "пять",
            "шесть",
            "семь",
            "восемь",
            "девять",
        )
        feminine_units = (
            "",
            "одна",
            "две",
            "три",
            "четыре",
            "пять",
            "шесть",
            "семь",
            "восемь",
            "девять",
        )

        result: list[str] = []
        hundred = number // 100
        remainder = number % 100
        if hundred:
            result.append(hundreds[hundred])

        if 10 <= remainder <= 19:
            result.append(teens[remainder - 10])
            return result

        ten = remainder // 10
        unit = remainder % 10
        if ten:
            result.append(tens[ten])
        if unit:
            units = feminine_units if gender == "feminine" else masculine_units
            result.append(units[unit])

        return result

    def _plural_form(
        self,
        number: int,
        singular: str,
        paucal: str,
        plural: str,
    ) -> str:
        last_two = number % 100
        if 11 <= last_two <= 14:
            return plural

        last_digit = number % 10
        if last_digit == 1:
            return singular
        if 2 <= last_digit <= 4:
            return paucal
        return plural
