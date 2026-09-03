"""Message and Inline Keyboard formatter for Offers Engine."""

from __future__ import annotations

from html import escape
from typing import List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.services.offers.models import CityOffers, JobType, Offer, generate_city_id


class OffersFormatter:
    """Formats Telegram responses and inline keyboards per spec sections 8, 9, 10."""

    @classmethod
    def format_city_prompt(cls, city_full: str) -> str:
        """Format city selection prompt text."""
        return f"📍 <b>{escape(city_full)}</b>\nВыберите проект"

    @classmethod
    def format_project_prompt(cls, city_full: str, project: str) -> str:
        """Format project selection prompt text."""
        return f"📍 <b>{escape(city_full)}</b>\n🏢 Проект: {escape(project)}\nВыберите вакансию"

    @classmethod
    def build_projects_keyboard(cls, city_offers: CityOffers) -> InlineKeyboardMarkup:
        buttons = []
        city_id = city_offers.city_id or generate_city_id(city_offers.city_clean)
        
        has_samokat = any(o.project == "Самокат" for o in city_offers.offers.values())
        has_lavka = any(o.project == "Яндекс Лавка" for o in city_offers.offers.values())
        
        if has_samokat:
            buttons.append([
                InlineKeyboardButton(
                    text="Самокат",
                    callback_data=f"off_proj:{city_id}:samokat",
                )
            ])
            
        if has_lavka:
            buttons.append([
                InlineKeyboardButton(
                    text="Яндекс Лавка",
                    callback_data=f"off_proj:{city_id}:lavka",
                )
            ])
            
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @classmethod
    def build_job_types_keyboard(cls, city_offers: CityOffers, project_filter: str = "samokat") -> InlineKeyboardMarkup:
        """Build inline keyboard with available job types for a given project."""
        buttons: List[List[InlineKeyboardButton]] = []
        city_id = city_offers.city_id or generate_city_id(city_offers.city_clean)

        if project_filter == "samokat":
            if JobType.VELO in city_offers.offers and city_offers.offers[JobType.VELO].project == "Самокат":
                buttons.append([InlineKeyboardButton(text="🚲 Вело-курьер", callback_data=f"off_job:{city_id}:samokat:velo")])
            if JobType.ELECTRO in city_offers.offers and city_offers.offers[JobType.ELECTRO].project == "Самокат":
                buttons.append([InlineKeyboardButton(text="⚡ Электро-велокурьер", callback_data=f"off_job:{city_id}:samokat:electro")])
            if JobType.VAHTA in city_offers.offers and city_offers.offers[JobType.VAHTA].project == "Самокат":
                buttons.append([InlineKeyboardButton(text="🏠 Вахта", callback_data=f"off_job:{city_id}:samokat:vahta")])
        elif project_filter == "lavka":
            if JobType.LAVKA_PICKER in city_offers.offers and city_offers.offers[JobType.LAVKA_PICKER].project == "Яндекс Лавка":
                buttons.append([InlineKeyboardButton(text="📦 Сборщик", callback_data=f"off_job:{city_id}:lavka:picker")])
            if JobType.LAVKA_COOK in city_offers.offers and city_offers.offers[JobType.LAVKA_COOK].project == "Яндекс Лавка":
                buttons.append([InlineKeyboardButton(text="🍳 Повар", callback_data=f"off_job:{city_id}:lavka:cook")])
                
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @classmethod
    def format_offer_details(cls, offer: Offer) -> str:
        """Format detailed offer details per spec section 9 & 10."""
        city_title = escape(offer.city_full)
        job_type_title = escape(offer.job_type.value)
        legal = escape(offer.legal_entity or "Не указано")
        r1 = escape(offer.rate_1 or "").strip()
        r2 = escape(offer.rate_2 or "").strip()
        r3 = escape(offer.rate_3 or "").strip()
        project_title = escape(offer.project)

        if offer.project == "Яндекс Лавка":
            rate_str = r1 or "—"
            return (
                f"🏢 <b>Проект:</b> {project_title}\n"
                f"📍 <b>Город:</b> {city_title}\n"
                f"👤 <b>Вакансия:</b> {job_type_title}\n\n"
                f"💰 <b>Ставка:</b>\n{rate_str}\n\n"
                f"🏛 <b>Юрлицо:</b>\n{legal}"
            )
        else:
            if r1 and r2 and r3 and r2 != "—" and r3 != "—":
                rate_str = f"{r1} + {r2}/{r3}"
            elif r1 and r2 and r2 != "—":
                rate_str = f"{r1} + {r2}"
            elif r1:
                rate_str = r1
            else:
                rate_str = "—"

            return (
                f"📍 <b>Город:</b> {city_title}\n"
                f"💼 <b>Тип работы:</b> {job_type_title}\n"
                f"🏢 <b>Юридическое лицо:</b> {legal}\n\n"
                f"💰 <b>Ставка:</b>\n{rate_str}"
            )

    @classmethod
    def format_not_found(cls, query_text: str, has_suggestions: bool) -> str:
        """Format text when city search yields no exact match."""
        q_esc = escape(query_text)
        if has_suggestions:
            return f"🔍 Город «<b>{q_esc}</b>» не найден. Возможно, вы имели в виду:"
        return f"❌ Город «<b>{q_esc}</b>» не найден в каталоге вакансий."

    @classmethod
    def build_city_suggestions_keyboard(cls, suggestions: List[CityOffers]) -> InlineKeyboardMarkup:
        """Build inline keyboard with suggested cities."""
        buttons = []
        for city in suggestions:
            city_id = city.city_id or generate_city_id(city.city_clean)
            buttons.append([
                InlineKeyboardButton(
                    text=f"📍 {city.city_full}",
                    callback_data=f"off_city:{city_id}",
                )
            ])
        return InlineKeyboardMarkup(inline_keyboard=buttons)
