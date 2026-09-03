from src.services.offers.models import CityOffers, Offer, JobType, generate_city_id
from src.services.offers.formatter import OffersFormatter

def test_callback_lengths_under_64_bytes():
    items = [
        ('off_job:москва:samokat:velo', 'Самокат Вело'),
        ('off_job:москва:samokat:electro', 'Самокат Электро'),
        ('off_job:москва:samokat:vahta', 'Самокат Вахта'),
        ('off_job:москва:lavka:picker', 'Лавка Сборщик'),
        ('off_job:москва:lavka:cook', 'Лавка Повар'),
        ('off_proj:санкт-петербург:samokat', 'СПб Проект Самокат'),
        ('off_proj:санкт-петербург:lavka', 'СПб Проект Лавка'),
    ]
    for cb, name in items:
        b_len = len(cb.encode('utf-8'))
        assert b_len <= 64, f'{cb} exceeds 64 bytes ({b_len})'

def test_scenario_samokat_only():
    c = CityOffers('Тверь', 'тверь')
    c.offers[JobType.VELO] = Offer('Тверь', 'тверь', JobType.VELO, 'ООО С', '100', '200', '300', 'Самокат')
    has_samokat = any(o.project == 'Самокат' for o in c.offers.values())
    has_lavka = any(o.project == 'Яндекс Лавка' for o in c.offers.values())
    assert has_samokat is True
    assert has_lavka is False
    kb = OffersFormatter.build_job_types_keyboard(c, 'samokat')
    assert len(kb.inline_keyboard) == 1
    assert kb.inline_keyboard[0][0].callback_data == f'off_job:{c.city_id}:samokat:velo'

def test_scenario_lavka_only():
    c = CityOffers('Иваново', 'иваново')
    c.offers[JobType.LAVKA_PICKER] = Offer('Иваново', 'иваново', JobType.LAVKA_PICKER, 'ООО Л', '150', '', '', 'Яндекс Лавка')
    has_samokat = any(o.project == 'Самокат' for o in c.offers.values())
    has_lavka = any(o.project == 'Яндекс Лавка' for o in c.offers.values())
    assert has_samokat is False
    assert has_lavka is True
    kb = OffersFormatter.build_job_types_keyboard(c, 'lavka')
    assert len(kb.inline_keyboard) == 1
    assert kb.inline_keyboard[0][0].callback_data == f'off_job:{c.city_id}:lavka:picker'

def test_scenario_mixed_city():
    c = CityOffers('Москва', 'москва')
    c.offers[JobType.VELO] = Offer('Москва', 'москва', JobType.VELO, 'ООО С', '100', '200', '300', 'Самокат')
    c.offers[JobType.LAVKA_PICKER] = Offer('Москва', 'москва', JobType.LAVKA_PICKER, 'ООО Л', '170', '', '', 'Яндекс Лавка')
    has_samokat = any(o.project == 'Самокат' for o in c.offers.values())
    has_lavka = any(o.project == 'Яндекс Лавка' for o in c.offers.values())
    assert has_samokat is True and has_lavka is True
    proj_kb = OffersFormatter.build_projects_keyboard(c)
    assert len(proj_kb.inline_keyboard) == 2
    assert proj_kb.inline_keyboard[0][0].callback_data == f'off_proj:{c.city_id}:samokat'
    assert proj_kb.inline_keyboard[1][0].callback_data == f'off_proj:{c.city_id}:lavka'