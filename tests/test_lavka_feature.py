import pytest
from unittest.mock import AsyncMock, MagicMock
from src.services.offers.models import JobType, Offer, OffersCatalogData, CityOffers, generate_city_id
from src.services.offers.parser import OffersParser, LavkaParser
from src.services.offers.formatter import OffersFormatter
from src.services.offers.service import OffersService
from src.services.offers.validators import OffersValidator
from aiogram.types import InlineKeyboardButton


def test_lavka_parser():
    rows = [
        ["Город", "Тип работы", "Юрлицо", "Ставка 1"],
        ["Москва", "Сборщик", "ООО Лавка", "172,50 ₽"],
        ["Москва", "Повар", "ООО Еда", "200 ₽"],
    ]
    parser = LavkaParser()
    catalog, issues = parser.parse(rows)
    
    assert len(catalog.cities) == 1
    moscow = catalog.get_city("москва")
    assert moscow is not None
    assert JobType.LAVKA_PICKER in moscow.offers
    
    picker_offer = moscow.offers[JobType.LAVKA_PICKER]
    assert picker_offer.project == "Яндекс Лавка"
    assert picker_offer.rate_1 == "172,50 ₽"
    assert picker_offer.legal_entity == "ООО Лавка"


def test_city_merge():
    samokat_rows = [
        ["Город", "Тип работы", "Юрлицо", "Ставка 1"],
        ["Москва", "Вело-курьер", "ООО Самокат", "100 ₽"],
    ]
    lavka_rows = [
        ["Город", "Тип работы", "Юрлицо", "Ставка 1"],
        ["Москва", "Сборщик", "ООО Лавка", "172,50 ₽"],
    ]
    
    samokat_parser = OffersParser()
    samokat_catalog, _ = samokat_parser.parse(samokat_rows)
    
    lavka_parser = LavkaParser()
    lavka_catalog, _ = lavka_parser.parse(lavka_rows)
    
    # Merge logic as in service
    for city_clean, city_offers in lavka_catalog.cities.items():
        if city_clean in samokat_catalog.cities:
            samokat_catalog.cities[city_clean].offers.update(city_offers.offers)
        else:
            samokat_catalog.cities[city_clean] = city_offers
            
    moscow = samokat_catalog.get_city("москва")
    assert JobType.VELO in moscow.offers
    assert JobType.LAVKA_PICKER in moscow.offers


def test_callbacks():
    city_offers = CityOffers("Москва", "москва")
    city_id = city_offers.city_id
    assert len(city_id) > 0
    city_offers.offers[JobType.VELO] = Offer("Москва", "москва", JobType.VELO, "Юр", "10", "20", "30", "Самокат")
    city_offers.offers[JobType.LAVKA_PICKER] = Offer("Москва", "москва", JobType.LAVKA_PICKER, "Юр", "10", "20", "30", "Яндекс Лавка")
    
    projects_kb = OffersFormatter.build_projects_keyboard(city_offers)
    assert len(projects_kb.inline_keyboard) == 2
    assert projects_kb.inline_keyboard[0][0].callback_data == f"off_proj:{city_id}:samokat"
    assert projects_kb.inline_keyboard[1][0].callback_data == f"off_proj:{city_id}:lavka"
    
    samokat_kb = OffersFormatter.build_job_types_keyboard(city_offers, "samokat")
    assert samokat_kb.inline_keyboard[0][0].callback_data == f"off_job:{city_id}:samokat:velo"
    
    lavka_kb = OffersFormatter.build_job_types_keyboard(city_offers, "lavka")
    assert lavka_kb.inline_keyboard[0][0].callback_data == f"off_job:{city_id}:lavka:picker"


def test_extremely_long_city_name_callback_under_64_bytes():
    # Longest city in Russia: Петропавловск-Камчатский (47 bytes in utf-8)
    city_offers = CityOffers("Петропавловск-Камчатский", "петропавловск-камчатский")
    city_id = city_offers.city_id
    city_offers.offers[JobType.ELECTRO] = Offer("Петропавловск-Камчатский", "петропавловск-камчатский", JobType.ELECTRO, "Юр", "10", "20", "30", "Самокат")
    city_offers.offers[JobType.LAVKA_PICKER] = Offer("Петропавловск-Камчатский", "петропавловск-камчатский", JobType.LAVKA_PICKER, "Юр", "10", "", "", "Яндекс Лавка")

    proj_kb = OffersFormatter.build_projects_keyboard(city_offers)
    for row in proj_kb.inline_keyboard:
        for btn in row:
            assert len(btn.callback_data.encode("utf-8")) <= 64

    job_kb = OffersFormatter.build_job_types_keyboard(city_offers, "samokat")
    for row in job_kb.inline_keyboard:
        for btn in row:
            assert len(btn.callback_data.encode("utf-8")) <= 64

    lavka_kb = OffersFormatter.build_job_types_keyboard(city_offers, "lavka")
    for row in lavka_kb.inline_keyboard:
        for btn in row:
            assert len(btn.callback_data.encode("utf-8")) <= 64


def test_formatter():
    city_offers = CityOffers("Москва", "москва")
    city_offers.offers[JobType.VELO] = Offer("Москва", "москва", JobType.VELO, "Юр", "10", "20", "30", "Самокат")
    
    # Only samokat
    samokat_kb = OffersFormatter.build_job_types_keyboard(city_offers, "samokat")
    assert len(samokat_kb.inline_keyboard) == 1
    
    # Now with Lavka
    city_offers.offers[JobType.LAVKA_PICKER] = Offer("Москва", "москва", JobType.LAVKA_PICKER, "Юр", "10", "20", "30", "Яндекс Лавка")
    lavka_kb = OffersFormatter.build_job_types_keyboard(city_offers, "lavka")
    assert len(lavka_kb.inline_keyboard) == 1
    
    # Test details formatter
    samokat_offer = city_offers.offers[JobType.VELO]
    samokat_text = OffersFormatter.format_offer_details(samokat_offer)
    assert "Тип работы" in samokat_text
    
    lavka_offer = city_offers.offers[JobType.LAVKA_PICKER]
    lavka_text = OffersFormatter.format_offer_details(lavka_offer)
    assert "Проект:</b> Яндекс Лавка" in lavka_text
    assert "Вакансия:</b> Сборщик" in lavka_text


def test_validator_lavka_single_rate():
    catalog = OffersCatalogData()
    moscow = CityOffers("Москва", "москва")
    # Lavka only has rate_1, rate_2 and rate_3 are empty
    moscow.offers[JobType.LAVKA_PICKER] = Offer("Москва", "москва", JobType.LAVKA_PICKER, "ООО Лавка", "150 ₽", "", "", "Яндекс Лавка")
    catalog.cities["москва"] = moscow
    
    validator = OffersValidator()
    # Should validate cleanly without rate_2/rate_3 warnings
    result = validator.validate(catalog, [])
    assert result is True


@pytest.mark.anyio
async def test_service_sheet_selection_scenarios():
    mock_auth = MagicMock()
    service = OffersService(mock_auth, sheet_id="test_sheet", poll_interval_seconds=10)

    # Scenario 1: Only Lavka sheet in workbook
    service.loader.get_sheet_names = AsyncMock(return_value=["Яндекс Лавка"])
    service.loader.fetch_rows = AsyncMock(return_value=[
        ["Город", "Тип работы", "Юрлицо", "Ставка 1"],
        ["Москва", "Сборщик", "ООО Лавка", "180 ₽"],
    ])
    
    success = await service.refresh_catalog()
    assert success is True
    moscow = service.catalog.get_city("москва")
    assert moscow is not None
    assert JobType.LAVKA_PICKER in moscow.offers
    assert moscow.offers[JobType.LAVKA_PICKER].project == "Яндекс Лавка"


def test_backward_compatibility():
    old_city = CityOffers("Казань", "казань")
    old_offer = Offer("Казань", "казань", JobType.VELO, "Ромашка", "1", "2", "3")
    old_city.offers[JobType.VELO] = old_offer
    
    assert old_offer.project == "Самокат"
    kb = OffersFormatter.build_job_types_keyboard(old_city, "samokat")
    assert kb.inline_keyboard[0][0].callback_data == f"off_job:{old_city.city_id}:samokat:velo"
    
    rows = [
        ["Город", "Тип работы", "Юрлицо", "Ставка 1"],
        ["Казань", "Вело", "Ромашка", "1"],
    ]
    parser = OffersParser()
    catalog, issues = parser.parse(rows)
    assert catalog.get_city("казань").offers[JobType.VELO].project == "Самокат"
    assert catalog.get_city_by_id(catalog.get_city("казань").city_id) is not None

