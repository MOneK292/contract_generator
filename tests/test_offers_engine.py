"""Unit tests for the Offers Engine module."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from src.interfaces.telegram.handlers.offers import (
    cmd_offers,
    handle_city_search_text,
    process_city_callback,
    process_job_callback,
)
from src.services.offers.cache import OffersCache
from src.services.offers.catalog import OffersCatalog
from src.services.offers.formatter import OffersFormatter
from src.services.offers.loader import OffersLoader
from src.services.offers.models import CityOffers, JobType, Offer, OffersCatalogData
from src.services.offers.parser import HeaderNotFoundError, OffersParser
from src.services.offers.service import OffersService
from src.services.offers.validators import OffersValidator


class OffersEngineTest(unittest.TestCase):
    """Unit test suite for Offers Engine components."""

    def test_job_type_normalization(self):
        self.assertEqual(JobType.normalize("Вело-курьер"), JobType.VELO)
        self.assertEqual(JobType.normalize("велокурьер"), JobType.VELO)
        self.assertEqual(JobType.normalize("Электро-велокурьер"), JobType.ELECTRO)
        self.assertEqual(JobType.normalize("электровело"), JobType.ELECTRO)
        self.assertEqual(JobType.normalize("Вахта"), JobType.VAHTA)
        self.assertEqual(JobType.normalize("вахта 15/15"), JobType.VAHTA)

        # Ignored per spec section 5
        self.assertIsNone(JobType.normalize("Вело-курьер (приоритет)"))
        self.assertIsNone(JobType.normalize("Вело-курьер (базовые ЦФЗ)"))
        self.assertIsNone(JobType.normalize("Пеший курьер"))
        self.assertIsNone(JobType.normalize("Водитель"))

    def test_city_name_cleaning(self):
        self.assertEqual(OffersParser.clean_city_name("Москва (Центр)"), "москва")
        self.assertEqual(OffersParser.clean_city_name("Санкт-Петербург (Север)"), "санкт-петербург")
        self.assertEqual(OffersParser.clean_city_name("  Тюмень  "), "тюмень")
        self.assertEqual(OffersParser.clean_city_name("Казань (Приоритет)"), "казань")

    def test_parser_dynamic_columns_and_success(self):
        parser = OffersParser()
        rows = [
            ["Юридическое лицо", "Город (населенный пункт)", "Ставка 1", "Тип вакансии", "Ставка 2", "Ставка 3"],
            ["ООО Ромашка (СПБ)", "Санкт-Петербург (Север)", "250 руб/час", "Вело-курьер", "35 руб/заказ", "3500 руб/день"],
            ["ООО Ромашка (СПБ)", "Санкт-Петербург", "300 руб/час", "Электро-велокурьер", "45 руб/заказ", "4500 руб/день"],
            ["ООО Вектор", "Санкт-Петербург", "3000 руб/смена", "Вахта", "50 руб/заказ", "50000 руб"],
            ["ООО Игнор", "Москва", "100", "Пеший курьер (приоритет)", "20", "2000"],
        ]

        catalog, issues = parser.parse(rows)
        self.assertEqual(len(catalog.cities), 1)
        spb = catalog.get_city("санкт-петербург")
        self.assertIsNotNone(spb)
        self.assertEqual(len(spb.offers), 3)
        self.assertIn(JobType.VELO, spb.offers)
        self.assertIn(JobType.ELECTRO, spb.offers)
        self.assertIn(JobType.VAHTA, spb.offers)

        velo = spb.offers[JobType.VELO]
        self.assertEqual(velo.legal_entity, "ООО Ромашка (СПБ)")
        self.assertEqual(velo.rate_1, "250 руб/час")
        self.assertEqual(velo.rate_2, "35 руб/заказ")
        self.assertEqual(velo.rate_3, "3500 руб/день")

    def test_parser_missing_required_column_raises(self):
        parser = OffersParser()
        rows = [
            ["Юрлицо", "Тип вакансии", "Ставка 1", "Ставка 2", "Ставка 3"],
            ["ООО Тест", "Вело-курьер", "100", "20", "300"],
        ]
        with self.assertRaises(HeaderNotFoundError):
            parser.parse(rows)

    def test_parser_duplicate_job_type_issues(self):
        parser = OffersParser()
        rows = [
            ["Город", "Тип вакансии", "Юрлицо", "Ставка 1", "Ставка 2", "Ставка 3"],
            ["Москва", "Вело-курьер", "ООО 1", "100", "20", "300"],
            ["Москва (Центр)", "Вело-курьер", "ООО 2", "150", "30", "400"],
        ]
        catalog, issues = parser.parse(rows)
        self.assertEqual(len(issues), 1)
        self.assertIn("Duplicate job type", issues[0])

    def test_validator_records_warnings(self):
        validator = OffersValidator()
        city_offers = CityOffers(city_full="Тюмень", city_clean="тюмень")
        city_offers.offers[JobType.VELO] = Offer(
            city_full="Тюмень",
            city_clean="тюмень",
            job_type=JobType.VELO,
            legal_entity="",  # Missing legal entity
            rate_1="200",
            rate_2="",       # Missing rate 2
            rate_3="3000",
        )
        catalog = OffersCatalogData(cities={"тюмень": city_offers})
        passed = validator.validate(catalog, parser_issues=["Some issue"])
        self.assertFalse(passed)

    def test_validator_clean_catalog(self):
        validator = OffersValidator()
        city_offers = CityOffers(city_full="Тюмень", city_clean="тюмень")
        city_offers.offers[JobType.VELO] = Offer(
            city_full="Тюмень",
            city_clean="тюмень",
            job_type=JobType.VELO,
            legal_entity="ООО Логистика (Тюмень)",
            rate_1="200 руб/ч",
            rate_2="35 руб/з",
            rate_3="3000 руб",
        )
        catalog = OffersCatalogData(cities={"тюмень": city_offers})
        passed = validator.validate(catalog, parser_issues=[])
        self.assertTrue(passed)

    def test_catalog_atomic_swap_and_cache_search(self):
        catalog = OffersCatalog()
        cache = OffersCache(catalog)

        # Initial empty search
        exact, suggestions = cache.find_city("Тюмень")
        self.assertIsNone(exact)
        self.assertEqual(suggestions, [])

        # Prepare data
        tyumen_clean = "тюмень"
        city_tyumen = CityOffers(city_full="Тюмень", city_clean=tyumen_clean)
        city_tyumen.offers[JobType.VELO] = Offer(
            city_full="Тюмень",
            city_clean=tyumen_clean,
            job_type=JobType.VELO,
            legal_entity="ООО Партнер",
            rate_1="200",
            rate_2="30",
            rate_3="2500",
        )

        moscow_clean = "москва"
        city_moscow = CityOffers(city_full="Москва (Центр)", city_clean=moscow_clean)
        city_moscow.offers[JobType.ELECTRO] = Offer(
            city_full="Москва (Центр)",
            city_clean=moscow_clean,
            job_type=JobType.ELECTRO,
            legal_entity="ООО Столица",
            rate_1="300",
            rate_2="50",
            rate_3="4000",
        )

        new_data = OffersCatalogData(cities={tyumen_clean: city_tyumen, moscow_clean: city_moscow})
        catalog.set_catalog(new_data)

        # Exact search with brackets in query
        exact, suggestions = cache.find_city("Москва (Север)")
        self.assertIsNotNone(exact)
        self.assertEqual(exact.city_full, "Москва (Центр)")
        self.assertIn(JobType.ELECTRO, exact.offers)

        # Exact search
        exact, _ = cache.find_city("Тюмень")
        self.assertIsNotNone(exact)
        self.assertEqual(exact.city_full, "Тюмень")

        # Fuzzy / Substring search
        exact, suggestions = cache.find_city("Моск")
        self.assertIsNone(exact)
        self.assertTrue(len(suggestions) > 0)
        self.assertEqual(suggestions[0].city_clean, "москва")

    def test_formatter_html_and_keyboard(self):
        offer = Offer(
            city_full="Москва (Центр)",
            city_clean="москва",
            job_type=JobType.VELO,
            legal_entity="ООО «Рога & Копыта»",
            rate_1="250 < 300",
            rate_2="40 руб",
            rate_3="4000 руб",
        )

        details = OffersFormatter.format_offer_details(offer)
        self.assertIn("📍 <b>Город:</b> Москва (Центр)", details)
        self.assertIn("💼 <b>Тип работы:</b> Вело-курьер", details)
        self.assertIn("ООО «Рога &amp; Копыта»", details)
        self.assertIn("250 &lt; 300", details)

        # Test keyboard with only VELO & ELECTRO (no VAHTA)
        city_offers = CityOffers(city_full="Москва", city_clean="москва")
        city_offers.offers[JobType.VELO] = offer
        city_offers.offers[JobType.ELECTRO] = offer

        kb = OffersFormatter.build_job_types_keyboard(city_offers)
        self.assertEqual(len(kb.inline_keyboard), 2)
        button_texts = [btn[0].text for btn in kb.inline_keyboard]
        self.assertIn("🚲 Вело-курьер", button_texts)
        self.assertIn("⚡ Электро-велокурьер", button_texts)
        self.assertNotIn("🏠 Вахта", button_texts)

        # Add VAHTA -> VAHTA button appears
        city_offers.offers[JobType.VAHTA] = offer
        kb_with_vahta = OffersFormatter.build_job_types_keyboard(city_offers)
        self.assertEqual(len(kb_with_vahta.inline_keyboard), 3)
        self.assertIn("🏠 Вахта", [btn[0].text for btn in kb_with_vahta.inline_keyboard])

    def test_offers_service_refresh_and_error_preservation(self):
        async def _test():
            mock_auth = MagicMock()
            service = OffersService(mock_auth, sheet_id="test_sheet", poll_interval_seconds=10)
    
            # Mock successful fetch
            valid_rows = [
                ["Город", "Тип вакансии", "Юрлицо", "Ставка 1", "Ставка 2", "Ставка 3"],
                ["Тюмень", "Вело-курьер", "ООО Тюм", "200", "30", "3000"],
            ]
            service.loader.fetch_rows = AsyncMock(return_value=valid_rows)
            service.loader.get_sheet_names = AsyncMock(return_value=["Самокат"])
    
            success = await service.refresh_catalog()
            self.assertTrue(success)
            exact, _ = service.find_city("Тюмень")
            self.assertIsNotNone(exact)

            # Next fetch fails with an exception -> catalog should be preserved
            service.loader.fetch_rows = AsyncMock(side_effect=Exception("Network error"))
            failed_sync = await service.refresh_catalog()
            self.assertFalse(failed_sync)
            # Verify previous working catalog is still intact
            exact, _ = service.find_city("Тюмень")
            self.assertIsNotNone(exact)

        asyncio.run(_test())

    def test_cmd_offers(self):
        async def _test():
            message = MagicMock(spec=Message)
            message.answer = AsyncMock()
            await cmd_offers(message)
            message.answer.assert_called_once()
            self.assertIn("Поиск вакансий и ставок", message.answer.call_args[0][0])

        asyncio.run(_test())

    def test_handle_city_search_exact_match(self):
        async def _test():
            mock_auth = MagicMock()
            service = OffersService(mock_auth, sheet_id="test_sheet")
            city_offers = CityOffers(city_full="Тюмень", city_clean="тюмень")
            city_offers.offers[JobType.VELO] = Offer(
                city_full="Тюмень",
                city_clean="тюмень",
                job_type=JobType.VELO,
                legal_entity="ООО Тест",
                rate_1="100",
                rate_2="20",
                rate_3="300",
            )
            service.catalog.set_catalog(OffersCatalogData(cities={"тюмень": city_offers}))

            storage = MemoryStorage()
            key = StorageKey(bot_id=1, chat_id=100, user_id=200)
            state = FSMContext(storage=storage, key=key)

            message = MagicMock(spec=Message)
            message.text = "Тюмень"
            message.answer = AsyncMock()

            await handle_city_search_text(message, state, offers_service=service)
            message.answer.assert_called_once()
            self.assertIn("📍 <b>Тюмень</b>", message.answer.call_args[1]["text"])

        asyncio.run(_test())

    def test_process_job_callback(self):
        async def _test():
            mock_auth = MagicMock()
            service = OffersService(mock_auth, sheet_id="test_sheet")
            city_offers = CityOffers(city_full="Тюмень", city_clean="тюмень")
            city_offers.offers[JobType.VELO] = Offer(
                city_full="Тюмень",
                city_clean="тюмень",
                job_type=JobType.VELO,
                legal_entity="ООО Логистика",
                rate_1="250",
                rate_2="40",
                rate_3="3500",
            )
            service.catalog.set_catalog(OffersCatalogData(cities={"тюмень": city_offers}))

            callback = MagicMock(spec=CallbackQuery)
            callback.data = "off_job:тюмень:velo"
            callback.answer = AsyncMock()
            callback.message = MagicMock(spec=Message)
            callback.message.answer = AsyncMock()

            await process_job_callback(callback, offers_service=service)
            callback.message.answer.assert_called_once()
            self.assertIn("ООО Логистика", callback.message.answer.call_args[1]["text"])
            callback.answer.assert_called_once()

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
