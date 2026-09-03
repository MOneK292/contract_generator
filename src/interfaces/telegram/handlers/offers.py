"""Telegram handlers for Offers Engine."""

from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.services.offers.formatter import OffersFormatter
from src.services.offers.models import JobType
from src.services.offers.service import OffersService

_logger = logging.getLogger(__name__)
offers_router = Router(name="offers")


@offers_router.message(Command("offers"))
async def cmd_offers(message: Message) -> None:
    """Show instructions for offers search."""
    await message.answer(
        "💼 <b>Поиск вакансий и ставок (Офферы)</b>\n\n"
        "Просто напишите название города в чат (например: <code>Тюмень</code> или <code>Москва</code>), "
        "и бот покажет доступные типы работы и условия оплаты.",
        parse_mode="HTML"
    )


@offers_router.callback_query(F.data.startswith("off_city:"))
async def process_city_callback(
    callback: CallbackQuery,
    offers_service: OffersService | None = None,
) -> None:
    """Handle click on a suggested city inline button."""
    if not offers_service:
        await callback.answer("Сервис офферов не активен", show_alert=True)
        return

    city_token = callback.data.split("off_city:")[1].strip()
    city_offers = offers_service.find_city_by_id(city_token)
    if not city_offers:
        city_offers, _ = offers_service.find_city(city_token)

    if not city_offers:
        await callback.answer("Информация по этому городу временно недоступна", show_alert=True)
        return

    has_samokat = any(o.project == "Самокат" for o in city_offers.offers.values())
    has_lavka = any(o.project == "Яндекс Лавка" for o in city_offers.offers.values())

    if has_samokat and has_lavka:
        # Show project selection
        text = OffersFormatter.format_city_prompt(city_offers.city_full)
        keyboard = OffersFormatter.build_projects_keyboard(city_offers)
    else:
        # Only one project, skip selection
        project_code = "samokat" if has_samokat else "lavka"
        project_name = "Самокат" if has_samokat else "Яндекс Лавка"
        text = OffersFormatter.format_project_prompt(city_offers.city_full, project_name)
        keyboard = OffersFormatter.build_job_types_keyboard(city_offers, project_code)

    await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@offers_router.callback_query(F.data.startswith("off_proj:"))
async def process_project_callback(
    callback: CallbackQuery,
    offers_service: OffersService | None = None,
) -> None:
    """Handle click on a project type inline button."""
    if not offers_service:
        await callback.answer("Сервис офферов не активен", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Неверная команда", show_alert=True)
        return

    city_token = parts[1]
    project_code = parts[2]

    city_offers = offers_service.find_city_by_id(city_token)
    if not city_offers:
        city_offers, _ = offers_service.find_city(city_token)

    if not city_offers:
        await callback.answer("Город не найден", show_alert=True)
        return

    project_name = "Самокат" if project_code == "samokat" else "Яндекс Лавка"
    text = OffersFormatter.format_project_prompt(city_offers.city_full, project_name)
    keyboard = OffersFormatter.build_job_types_keyboard(city_offers, project_code)

    await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@offers_router.callback_query(F.data.startswith("off_job:"))
async def process_job_callback(
    callback: CallbackQuery,
    offers_service: OffersService | None = None,
) -> None:
    """Handle click on a job type inline button."""
    if not offers_service:
        await callback.answer("Сервис офферов не активен", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Неверная команда", show_alert=True)
        return

    city_token = parts[1]
    # backward compatibility: off_job:moscow:velo -> parts=[off_job, moscow, velo]
    if len(parts) == 3:
        project_code = "samokat"
        job_key = parts[2]
    else:
        project_code = parts[2]
        job_key = parts[3]

    city_offers = offers_service.find_city_by_id(city_token)
    if not city_offers:
        city_offers, _ = offers_service.find_city(city_token)

    if not city_offers:
        await callback.answer("Город не найден", show_alert=True)
        return

    target_type = None
    if job_key == "velo":
        target_type = JobType.VELO
    elif job_key == "electro":
        target_type = JobType.ELECTRO
    elif job_key == "vahta":
        target_type = JobType.VAHTA
    elif job_key == "picker":
        target_type = JobType.LAVKA_PICKER
    elif job_key == "cook":
        target_type = JobType.LAVKA_COOK

    offer = city_offers.offers.get(target_type) if target_type else None
    if not offer:
        await callback.answer("Оффер для данного типа работы не найден", show_alert=True)
        return

    text = OffersFormatter.format_offer_details(offer)
    await callback.message.answer(text=text, parse_mode="HTML")
    await callback.answer()


@offers_router.message(F.text, ~F.text.startswith("/"))
async def handle_city_search_text(
    message: Message,
    state: FSMContext,
    offers_service: OffersService | None = None,
) -> None:
    """
    Handle plain text city search when user is not in an active FSM wizard state.
    """
    current_state = await state.get_state()
    if current_state is not None:
        # User is in FSM wizard (e.g. filling contract fields or schedule settings), pass through
        return

    if not offers_service:
        return

    text = (message.text or "").strip()
    if not text or len(text) < 2:
        return

    city_offers, suggestions = offers_service.find_city(text)

    if city_offers:
        has_samokat = any(o.project == "Самокат" for o in city_offers.offers.values())
        has_lavka = any(o.project == "Яндекс Лавка" for o in city_offers.offers.values())

        if has_samokat and has_lavka:
            # Show project selection
            prompt_text = OffersFormatter.format_city_prompt(city_offers.city_full)
            keyboard = OffersFormatter.build_projects_keyboard(city_offers)
        else:
            # Only one project, skip selection
            project_code = "samokat" if has_samokat else "lavka"
            project_name = "Самокат" if has_samokat else "Яндекс Лавка"
            prompt_text = OffersFormatter.format_project_prompt(city_offers.city_full, project_name)
            keyboard = OffersFormatter.build_job_types_keyboard(city_offers, project_code)
            
        await message.answer(text=prompt_text, reply_markup=keyboard, parse_mode="HTML")
    elif suggestions:
        not_found_text = OffersFormatter.format_not_found(text, has_suggestions=True)
        keyboard = OffersFormatter.build_city_suggestions_keyboard(suggestions)
        await message.answer(text=not_found_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        # City not found and no suggestions
        not_found_text = OffersFormatter.format_not_found(text, has_suggestions=False)
        await message.answer(text=not_found_text, parse_mode="HTML")
