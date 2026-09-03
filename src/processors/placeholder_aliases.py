"""Explicit placeholder alias rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping


AliasRule = Callable[[Mapping[str, str]], str | None]


def _join_fields(*field_names: str) -> AliasRule:
    def rule(data: Mapping[str, str]) -> str | None:
        values = [str(data.get(field_name, "")).strip() for field_name in field_names]
        if not all(values):
            return None
        return " ".join(values)

    return rule


def _copy_field(field_name: str) -> AliasRule:
    def rule(data: Mapping[str, str]) -> str | None:
        value = str(data.get(field_name, "")).strip()
        return value or None

    return rule


def _first_field(*field_names: str) -> AliasRule:
    """Return the value of the first non-empty field."""
    def rule(data: Mapping[str, str]) -> str | None:
        for name in field_names:
            value = str(data.get(name, "")).strip()
            if value:
                return value
        return None

    return rule


PLACEHOLDER_ALIASES: dict[str, AliasRule] = {
    "ФИО": _join_fields("Ф", "И", "О"),
    "Серия, номер П": _join_fields("Серия", "Номер П"),
    "Плата": _copy_field("Ставка"),
    # Компоненты даты: плейсхолдер <День> берётся из "Дата выдачи" или явного "День"
    "День": _first_field("Дата выдачи День", "День"),
    "Месяц": _first_field("Дата выдачи Месяц", "Месяц"),
    "Год": _first_field("Дата выдачи Год", "Год"),
    "МесяцЧ": _first_field("Дата выдачи МесяцЧ", "МесяцЧ"),
}

PLACEHOLDER_ALIAS_SOURCES: dict[str, tuple[str, ...]] = {
    "ФИО": ("Ф", "И", "О"),
    "Серия, номер П": ("Серия", "Номер П"),
    "Плата": ("Ставка",),
    "День": ("Дата выдачи День", "День"),
    "Месяц": ("Дата выдачи Месяц", "Месяц"),
    "Год": ("Дата выдачи Год", "Год"),
    "МесяцЧ": ("Дата выдачи МесяцЧ", "МесяцЧ"),
}
