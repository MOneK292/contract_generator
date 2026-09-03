"""Tests for employee parsing and field processors."""

from __future__ import annotations

import unittest

from src.core.processor_registry import ProcessorRegistry
from src.parsers.employee_parser import EmployeeParser
from src.processors.date_processor import DateProcessor
from src.processors.fio_processor import FioProcessor
from src.processors.money_processor import MoneyProcessor
from src.processors.placeholder_processor import PlaceholderProcessor


class EmployeeParserTest(unittest.TestCase):
    """Employee parser behavior."""

    def test_parses_text_fields_without_changing_values(self) -> None:
        parser = EmployeeParser()

        result = parser.parse(
            "\n".join(
                [
                    "ФИО: Иванова Анна Сергеевна",
                    "Номер: 79990000002",
                    "Ставка: 316,00",
                    "Город: Санкт-Петербург",
                ]
            )
        )

        self.assertEqual(result["ФИО"], "Иванова Анна Сергеевна")
        self.assertEqual(result["Номер"], "79990000002")
        self.assertEqual(result["Ставка"], "316,00")
        self.assertEqual(result["Город"], "Санкт-Петербург")

    def test_parses_unknown_fields(self) -> None:
        parser = EmployeeParser()

        result = parser.parse("Размер обуви: 42")

        self.assertEqual(result, {"Размер обуви": "42"})

    def test_parses_tolerant_input_and_aliases(self) -> None:
        parser = EmployeeParser()

        result = parser.parse(
            "\n".join(
                [
                    "Иванов Иван Иванович 79990000001",
                    "Паспорт: 445467890",
                    "Выдан: Отделом УФМС",
                    "ИНН - 123456789012",
                    "СНИЛС - 166-865-355 19",
                    "Почта - candidate@example.com",
                ]
            )
        )

        self.assertEqual(result["ФИО"], "Иванов Иван Иванович")
        self.assertEqual(result["Телефон"], "79990000001")
        self.assertEqual(result["Серия, номер П"], "445467890")
        self.assertEqual(result["Кем выдан"], "Отделом УФМС")
        self.assertEqual(result["ИНН"], "123456789012")
        self.assertEqual(result["СНИЛС"], "166-865-355 19")
        self.assertEqual(result["Почта"], "candidate@example.com")

    def test_ignores_empty_values(self) -> None:
        parser = EmployeeParser()

        result = parser.parse("Город:\nДата рождения:")

        self.assertEqual(result, {})


class FioProcessorTest(unittest.TestCase):
    """FIO processor behavior."""

    def test_adds_short_fio_fields(self) -> None:
        result = FioProcessor().process({"ФИО": "Иванов Иван Иванович"})

        self.assertEqual(result["Ф"], "Иванов")
        self.assertEqual(result["И"], "Иван")
        self.assertEqual(result["О"], "Иванович")

    def test_does_nothing_without_fio(self) -> None:
        data = {"Город": "Санкт-Петербург"}

        self.assertEqual(FioProcessor().process(data), data)


class DateProcessorTest(unittest.TestCase):
    """Date processor behavior."""

    def test_adds_date_components_for_every_date_field(self) -> None:
        result = DateProcessor().process(
            {
                "Дата выдачи": "15.04.2021",
                "Дата рождения": "02.07.2001",
            }
        )

        self.assertEqual(result["Дата выдачи День"], "15")
        self.assertEqual(result["Дата выдачи Месяц"], "апреля")
        self.assertEqual(result["Дата выдачи МесяцЧ"], "04")
        self.assertEqual(result["Дата выдачи Год"], "2021")
        self.assertEqual(result["Дата рождения День"], "02")
        self.assertEqual(result["Дата рождения Месяц"], "июля")
        self.assertEqual(result["Дата рождения МесяцЧ"], "07")
        self.assertEqual(result["Дата рождения Год"], "2001")

    def test_issue_date_does_not_fill_common_contract_date_placeholders(self) -> None:
        result = DateProcessor().process({"Дата выдачи": "15.04.2021"})

        self.assertNotIn("День", result)
        self.assertNotIn("Месяц", result)
        self.assertNotIn("МесяцЧ", result)
        self.assertNotIn("Год", result)


class MoneyProcessorTest(unittest.TestCase):
    """Money processor behavior."""

    def test_normalizes_money_format(self) -> None:
        processor = MoneyProcessor()

        self.assertEqual(processor.process({"Ставка": "316"})["Ставка"], "316,00 (триста шестнадцать рублей, ноль копеек)")
        self.assertEqual(processor.process({"Ставка": "316.5"})["Ставка"], "316,50 (триста шестнадцать рублей, пятьдесят копеек)")
        self.assertEqual(processor.process({"Ставка": "316,5"})["Ставка"], "316,50 (триста шестнадцать рублей, пятьдесят копеек)")

    def test_adds_money_words(self) -> None:
        result = MoneyProcessor().process({"Ставка": "316,00"})

        self.assertEqual(
            result["Ставка Прописью"],
            "триста шестнадцать рублей, ноль копеек",
        )


class PlaceholderProcessorTest(unittest.TestCase):
    """Placeholder compatibility processor behavior."""

    def test_adds_derived_placeholder_fields_without_overwriting_values(self) -> None:
        result = PlaceholderProcessor().process(
            {
                "Ф": "Иванов",
                "И": "Иван",
                "О": "Иванович",
                "ФИО": "Existing",
                "Серия": "4454",
                "Номер П": "67890",
                "Ставка": "316,00",
            }
        )

        self.assertEqual(result["ФИО"], "Existing")
        self.assertEqual(result["Серия, номер П"], "4454 67890")
        self.assertEqual(result["Плата"], "316,00")

    def test_does_not_create_unconfigured_date_aliases(self) -> None:
        result = PlaceholderProcessor().process(
            {
                "День": "14",
                "Месяц": "июля",
                "Год": "2026",
            }
        )

        self.assertNotIn("День1", result)
        self.assertNotIn("Месяц1", result)
        self.assertNotIn("Год1", result)

    def test_adds_fio_when_short_fields_exist(self) -> None:
        result = PlaceholderProcessor().process(
            {
                "Ф": "Сорнева",
                "И": "Мария",
                "О": "Игоревна",
            }
        )

        self.assertEqual(result["ФИО"], "Сорнева Мария Игоревна")


class ProcessorRegistryTest(unittest.TestCase):
    """Processor registry behavior."""

    def test_applies_registered_processors_in_order(self) -> None:
        parser = EmployeeParser()
        registry = ProcessorRegistry()
        registry.register(FioProcessor())
        registry.register(DateProcessor())
        registry.register(MoneyProcessor())

        raw_data = parser.parse(
            "\n".join(
                [
                    "ФИО: Бушина Ангелина Георгиевна",
                    "Ставка: 316,00",
                    "Дата выдачи: 15.04.2021",
                    "Размер обуви: 42",
                ]
            )
        )
        result = registry.process(raw_data)

        self.assertEqual(result["Ф"], "Бушина")
        self.assertEqual(result["И"], "Ангелина")
        self.assertEqual(result["О"], "Георгиевна")
        self.assertEqual(result["Дата выдачи Месяц"], "апреля")
        self.assertEqual(result["Ставка"], "316,00 (триста шестнадцать рублей, ноль копеек)")
        self.assertEqual(
            result["Ставка Прописью"],
            "триста шестнадцать рублей, ноль копеек",
        )
        self.assertEqual(result["Размер обуви"], "42")


if __name__ == "__main__":
    unittest.main()
