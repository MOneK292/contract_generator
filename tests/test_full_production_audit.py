import asyncio
import threading
from src.services.offers.models import CityOffers, Offer, JobType, OffersCatalogData, ProjectType
from src.services.offers.parser import OffersParser, LavkaParser, HeaderNotFoundError
from src.services.offers.catalog import OffersCatalog
from src.services.offers.cache import OffersCache
from src.services.offers.formatter import OffersFormatter
from src.services.offers.validators import OffersValidator

def test_callback_data_standard_cities():
    cities = ['москва', 'санкт-петербург', 'нижний новгород', 'ростов-на-дону', 'новосибирск', 'екатеринбург']
    jobs = ['velo', 'electro', 'vahta', 'picker', 'cook']
    projs = ['samokat', 'lavka']
    
    for city in cities:
        for proj in projs:
            cd_proj = f'off_proj:{city}:{proj}'
            assert len(cd_proj.encode('utf-8')) <= 64, f'{cd_proj} exceeds 64 bytes'
            for job in jobs:
                cd_job = f'off_job:{city}:{proj}:{job}'
                assert len(cd_job.encode('utf-8')) <= 64, f'{cd_job} exceeds 64 bytes'

def test_backward_compatibility_old_callbacks():
    old_cd = 'off_job:москва:velo'
    parts = old_cd.split(':')
    assert len(parts) == 3
    city_clean = parts[1]
    if len(parts) == 3:
        project_code = 'samokat'
        job_key = parts[2]
    else:
        project_code = parts[2]
        job_key = parts[3]
    assert city_clean == 'москва'
    assert project_code == 'samokat'
    assert job_key == 'velo'

def test_empty_sheet_handling():
    parser = OffersParser()
    try:
        parser.parse([])
        assert False, 'Should raise HeaderNotFoundError'
    except HeaderNotFoundError:
        pass

def test_atomic_swap_and_concurrency():
    catalog = OffersCatalog()
    d1 = OffersCatalogData()
    d1.cities['москва'] = CityOffers('Москва', 'москва')
    catalog.set_catalog(d1)
    
    errors = []
    def reader_thread():
        for _ in range(1000):
            c = catalog.get_city('москва')
            if c is None:
                errors.append('Catalog snapshot returned None during read')
                
    def writer_thread():
        for i in range(500):
            d2 = OffersCatalogData()
            d2.cities['москва'] = CityOffers('Москва', 'москва')
            d2.cities[f'город_{i}'] = CityOffers(f'Город {i}', f'город_{i}')
            catalog.set_catalog(d2)
            
    t1 = threading.Thread(target=reader_thread)
    t2 = threading.Thread(target=writer_thread)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(errors) == 0

def test_nonetype_and_keyerror_resilience():
    offer = Offer(
        city_full='Казань',
        city_clean='казань',
        job_type=JobType.LAVKA_PICKER,
        legal_entity='',
        rate_1='',
        rate_2='',
        rate_3='',
        project='Яндекс Лавка'
    )
    formatted = OffersFormatter.format_offer_details(offer)
    assert 'Не указано' in formatted or '—' in formatted
    assert 'Яндекс Лавка' in formatted

def test_duplicate_jobs_in_sheet():
    rows = [
        ['Город', 'Тип работы', 'Юрлицо', 'Ставка 1'],
        ['Москва', 'Сборщик', 'ООО 1', '100'],
        ['Москва', 'Сборщик', 'ООО 2', '200'],
    ]
    parser = LavkaParser()
    cat, issues = parser.parse(rows)
    assert len(issues) == 1
    assert 'Duplicate' in issues[0]
    assert cat.get_city('москва').offers[JobType.LAVKA_PICKER].rate_1 == '100'