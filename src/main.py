"""Production entry point for the contract generator Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from src.core.contract_engine import ContractEngine
from src.core.exceptions import ConfigurationError
from src.core.processor_registry import ProcessorRegistry
from src.diagnostics import DiagnosticsRunner, print_report
from src.interfaces.telegram import (
    TelegramStartupError,
    create_telegram_application,
    run_polling,
)
from src.parsers.employee_parser import EmployeeParser
from src.processors.date_processor import DateProcessor
from src.processors.fio_processor import FioProcessor
from src.processors.money_processor import MoneyProcessor
from src.processors.placeholder_processor import PlaceholderProcessor
from src.services.cleanup.cleanup_service import CleanupService
from src.services.config import AppConfig, TemplateCatalog
from src.services.config.settings_loader import SettingsLoader
from src.services.docx.renderer import DocxRenderer
from src.services.google.auth import GoogleAuth
from src.services.google.cache import TemplateCache
from src.services.google.catalog import GoogleDriveCatalogService
from src.services.google.drive import GoogleDriveService
from src.services.logging.setup import LoggingSetup
from src.services.pdf.converter import PdfConverter
from src.services.offers import OffersService
from src.services.schedule_tracker import (
    GoogleSheetsClient,
    SchedulePoller,
    ScheduleRepository,
    ScheduleTrackerService,
)


@dataclass(frozen=True)
class ApplicationComposition:
    """Production application dependencies created in the composition root."""

    config: AppConfig
    template_catalog: TemplateCatalog
    contract_engine: ContractEngine


def create_application(config: AppConfig | None = None) -> ApplicationComposition:
    """Create the production contract engine and all its dependencies."""
    root_dir = Path(__file__).resolve().parents[1]
    config = config or SettingsLoader(root_dir=root_dir).load()
    LoggingSetup.configure(config.logging, config.paths.logs_dir)

    drive_client = GoogleAuth(config).create_drive_client()
    drive_service = GoogleDriveService(drive_client)
    template_catalog = GoogleDriveCatalogService(
        config,
        drive_service,
    ).load_catalog()
    template_cache = TemplateCache(config, drive_service)

    processor_registry = ProcessorRegistry()
    processor_registry.register(FioProcessor())
    processor_registry.register(DateProcessor())
    processor_registry.register(MoneyProcessor())
    processor_registry.register(PlaceholderProcessor())
    pdf_converter = create_pdf_converter(config)

    contract_engine = ContractEngine(
        template_catalog=template_catalog,
        template_cache=template_cache,
        employee_parser=EmployeeParser(),
        processor_registry=processor_registry,
        docx_renderer=DocxRenderer(),
        pdf_converter=pdf_converter,
        cleanup_service=CleanupService(),
        output_dir=config.paths.temp_dir,
        pdf_output_dir=config.paths.temp_dir,
    )
    return ApplicationComposition(
        config=config,
        template_catalog=template_catalog,
        contract_engine=contract_engine,
    )


def create_pdf_converter(config: AppConfig) -> PdfConverter:
    """Create PdfConverter (LibreOffice or docx2pdf fallback)."""
    return PdfConverter(config)


async def async_main() -> None:
    """Run diagnostics, create dependencies and start Telegram polling & background workers."""
    root_dir = Path(__file__).resolve().parents[1]
    try:
        config = SettingsLoader(root_dir=root_dir).load()
        LoggingSetup.configure(config.logging, config.paths.logs_dir)
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    diagnostics_report = DiagnosticsRunner(root_dir=root_dir).run()
    print_report(diagnostics_report)
    if diagnostics_report.has_errors():
        print("Diagnostics failed. Telegram startup cancelled.", file=sys.stderr)
        raise SystemExit(1)

    try:
        application = create_application(config)

        tracker_service: ScheduleTrackerService | None = None
        if config.schedule.enabled:
            sheets_client = GoogleSheetsClient(
                google_auth=GoogleAuth(config),
            )
            schedule_repo = ScheduleRepository(config.paths.cache_dir / "schedule_state.db")
            tracker_service = ScheduleTrackerService(
                sheets_client=sheets_client,
                spreadsheet_id=config.schedule.sheet_id,
                manager_name=config.schedule.manager_name,
                timezone=config.schedule.timezone,
                repository=schedule_repo,
            )

        offers_service: OffersService | None = None
        if hasattr(config, "offers") and config.offers.enabled:
            offers_service = OffersService(
                google_auth=GoogleAuth(config),
                sheet_id=config.offers.sheet_id,
                poll_interval_seconds=config.offers.poll_interval_seconds,
                enabled=config.offers.enabled,
                samokat_sheet=getattr(config.offers, "samokat_sheet", ""),
                lavka_sheet=getattr(config.offers, "lavka_sheet", ""),
            )
            try:
                await offers_service.initialize()
                await offers_service.start_background_polling()
            except Exception as error:
                logging.getLogger(__name__).warning("Offers service initial sync failed: %s", error)

        telegram_application = create_telegram_application(
            application.config,
            application.template_catalog,
            application.contract_engine,
            schedule_tracker=tracker_service,
            offers_service=offers_service,
        )

        # Initialize and start Google Sheets Schedule Tracker background worker
        if config.schedule.enabled and tracker_service is not None:
            schedule_poller = SchedulePoller(
                bot=telegram_application.bot,
                tracker=tracker_service,
                recipients=config.auth.authorized_users,
                interval_seconds=config.schedule.poll_interval_seconds,
                enabled=config.schedule.enabled,
                notification_start_time=config.schedule.notification_start_time,
                notification_end_time=config.schedule.notification_end_time,
            )
            asyncio.create_task(schedule_poller.start())
            logging.getLogger(__name__).info("Google Sheets schedule poller task spawned with SQLite persistence")

        logging.getLogger(__name__).info("Application created successfully")
        await run_polling(telegram_application)
    except (ConfigurationError, TelegramStartupError) as error:
        logging.getLogger(__name__).error("Startup failed: %s", error)
        print(f"Startup error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def main() -> None:
    """Run the production Telegram bot."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
