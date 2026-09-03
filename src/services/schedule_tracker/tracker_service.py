"""Schedule tracker business logic, state management, SQLite persistence, and diff engine."""

from __future__ import annotations

import logging
import re
from typing import Any

from src.services.schedule_tracker.models import (
    ChangeType,
    ScheduleDiff,
    ScheduleReport,
    ScheduleSlot,
)
from src.services.schedule_tracker.phone_extractor import extract_and_format_phones
from src.services.schedule_tracker.repository import ScheduleRepository
from src.services.schedule_tracker.sheets_client import GoogleSheetsClient
from src.services.schedule_tracker.time_utils import (
    clean_cell_text,
    get_moscow_iso_week,
    get_moscow_today_str,
    parse_time_slot,
)

_logger = logging.getLogger(__name__)


class ScheduleTrackerService:
    """Core tracking service detecting differences in manager schedule with SQLite persistence."""

    def __init__(
        self,
        sheets_client: GoogleSheetsClient,
        spreadsheet_id: str,
        manager_name: str = "Manager",
        timezone: str = "Europe/Moscow",
        repository: ScheduleRepository | None = None,
    ) -> None:
        self.sheets_client = sheets_client
        self.spreadsheet_id = spreadsheet_id
        self.manager_name = manager_name.strip()
        self.timezone = timezone
        self.repository = repository

        self._last_date: str | None = None
        self._last_schedule: dict[str, str] | None = None
        self._initialized: bool = False

    async def _ensure_state_loaded(self, today_str: str) -> None:
        """Load persisted schedule state from SQLite if available."""
        if not self._initialized:
            self._last_date = today_str
            if self.repository:
                saved = await self.repository.load_schedule(self.manager_name, today_str)
                if saved:
                    _logger.info(
                        "Restored %d schedule slots from SQLite for %s (%s)",
                        len(saved),
                        self.manager_name,
                        today_str,
                    )
                    self._last_schedule = saved
            self._initialized = True

    def _find_target_sheet_name(self, sheet_names: list[str], week_number: int) -> str | None:
        """Find sheet title matching 'Неделя XX'."""
        target_pattern = re.compile(rf"^неделя\s*{week_number}$", re.IGNORECASE)
        for name in sheet_names:
            normalized = name.strip().lower()
            if target_pattern.match(normalized):
                return name

        target_sub = f"неделя {week_number}".lower()
        for name in sheet_names:
            if target_sub in name.strip().lower():
                return name

        return None

    def _is_date_matching(self, cell_value: Any, today_str: str) -> bool:
        """Check if a cell contains today's date."""
        if not cell_value:
            return False
        val_str = str(cell_value).strip()
        if today_str in val_str:
            return True

        day, month, year = today_str.split(".")
        day_no_zero = str(int(day))
        month_no_zero = str(int(month))
        year_short = year[-2:]

        patterns = [
            f"{day_no_zero}.{month_no_zero}.{year}",
            f"{day}.{month}.{year_short}",
            f"{day_no_zero}.{month_no_zero}.{year_short}",
        ]
        return any(p in val_str for p in patterns)

    def _is_any_date_cell(self, cell_value: Any) -> bool:
        """Check if a cell contains any date string DD.MM.YYYY."""
        if not cell_value:
            return False
        val_str = str(cell_value).strip()
        return bool(re.search(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b", val_str))

    def _parse_sheet_data(
        self, rows: list[list[Any]], today_str: str
    ) -> tuple[dict[str, str], list[ScheduleSlot]] | None:
        """Locate header time columns and manager row for today."""
        if not rows or len(rows) < 2:
            return None

        manager_lower = self.manager_name.lower()

        # 1. Find section for today's date
        today_date_row_idx: int | None = None
        for r_idx, row in enumerate(rows):
            if any(self._is_date_matching(cell, today_str) for cell in row):
                today_date_row_idx = r_idx
                break

        if today_date_row_idx is not None:
            # Determine end of section (next date row or end of sheet)
            next_date_row_idx = len(rows)
            for r_idx in range(today_date_row_idx + 1, len(rows)):
                if any(self._is_any_date_cell(cell) for cell in rows[r_idx]):
                    next_date_row_idx = r_idx
                    break

            # Find manager row inside today's section (checking today_date_row_idx as well)
            target_row: list[Any] | None = None
            for r_idx in range(today_date_row_idx, next_date_row_idx):
                row = rows[r_idx]
                row_str = " ".join(str(c) for c in row).lower()
                if manager_lower in row_str:
                    target_row = row
                    break

            if target_row is not None:
                # Build time col map from today's date row
                time_col_map: dict[int, str] = {}
                for col_idx, cell in enumerate(rows[today_date_row_idx]):
                    slot_time = parse_time_slot(cell)
                    if slot_time:
                        time_col_map[col_idx] = slot_time

                if not time_col_map:
                    # Fallback to nearest header row above
                    for r_idx in range(today_date_row_idx, -1, -1):
                        col_map = {}
                        for col_idx, cell in enumerate(rows[r_idx]):
                            slot_time = parse_time_slot(cell)
                            if slot_time:
                                col_map[col_idx] = slot_time
                        if len(col_map) > len(time_col_map):
                            time_col_map = col_map
                            break

                current_schedule: dict[str, str] = {}
                all_slots: list[ScheduleSlot] = []

                for col_idx, time_str in time_col_map.items():
                    val = target_row[col_idx] if col_idx < len(target_row) else ""
                    cleaned = clean_cell_text(val)
                    if cleaned:
                        current_schedule[time_str] = cleaned
                        all_slots.append(ScheduleSlot(time=time_str, value=cleaned))

                all_slots.sort(key=lambda s: s.time)
                return current_schedule, all_slots

        _logger.debug(
            "No row found for manager '%s' on date %s",
            self.manager_name,
            today_str,
        )
        return None

    async def commit_report(self, report: ScheduleReport) -> None:
        """Commit new schedule state after confirmed successful delivery."""
        self._last_schedule = report.new_schedule
        self._last_date = report.date
        if self.repository:
            await self.repository.save_schedule(self.manager_name, report.date, report.new_schedule)
            _logger.debug(
                "Committed %d schedule slots to SQLite for %s on %s",
                len(report.new_schedule),
                self.manager_name,
                report.date,
            )

    async def check_for_updates(self) -> ScheduleReport | None:
        """Check Google Sheets for schedule changes without committing state prematurely."""
        today_str = get_moscow_today_str(self.timezone)
        week_num = get_moscow_iso_week(self.timezone)

        await self._ensure_state_loaded(today_str)

        # 1. Reset state when day rolls over
        if self._last_date is not None and self._last_date != today_str:
            _logger.info("New day detected (%s -> %s), resetting tracker state", self._last_date, today_str)
            self._last_date = today_str
            self._last_schedule = None
            if self.repository:
                saved = await self.repository.load_schedule(self.manager_name, today_str)
                if saved:
                    self._last_schedule = saved
                # Clean up records older than 30 days
                await self.repository.cleanup_old_records(days_to_keep=30)

        # 2. Get available sheets
        sheet_names = await self.sheets_client.get_sheet_names(self.spreadsheet_id)
        target_sheet = self._find_target_sheet_name(sheet_names, week_num)
        if not target_sheet:
            _logger.warning(
                "Sheet for week %d not found in spreadsheet. Available sheets: %s",
                week_num,
                sheet_names,
            )
            return None

        # 3. Read sheet data
        rows = await self.sheets_client.get_sheet_values(self.spreadsheet_id, target_sheet)
        parsed = self._parse_sheet_data(rows, today_str)
        if parsed is None:
            return None

        current_schedule, all_slots = parsed

        # 4. Cold start baseline snapshot (if no prior state in DB or memory)
        if self._last_schedule is None:
            _logger.info(
                "Initializing baseline schedule snapshot (%d slots) for %s on %s",
                len(current_schedule),
                self.manager_name,
                today_str,
            )
            self._last_schedule = current_schedule
            if self.repository:
                await self.repository.save_schedule(self.manager_name, today_str, current_schedule)
            return None

        # 5. Compute diffs
        diffs: list[ScheduleDiff] = []

        # Check new & modified slots
        for time_str, new_val in current_schedule.items():
            old_val = self._last_schedule.get(time_str)
            if old_val != new_val:
                change_type = ChangeType.NEW if not old_val else ChangeType.MODIFIED
                diffs.append(
                    ScheduleDiff(
                        time=time_str,
                        old_value=old_val,
                        new_value=new_val,
                        change_type=change_type,
                    )
                )

        # Check deleted slots
        for time_str, old_val in self._last_schedule.items():
            if old_val and (time_str not in current_schedule or not current_schedule[time_str]):
                diffs.append(
                    ScheduleDiff(
                        time=time_str,
                        old_value=old_val,
                        new_value=None,
                        change_type=ChangeType.DELETED,
                    )
                )

        if not diffs:
            # Sync schedule if identical to keep DB fresh
            if self.repository and self._last_schedule != current_schedule:
                await self.repository.save_schedule(self.manager_name, today_str, current_schedule)
            self._last_schedule = current_schedule
            return None

        diffs.sort(key=lambda d: d.time)

        # 6. Extract phone numbers
        texts_to_scan = list(current_schedule.values()) + [
            d.new_value for d in diffs if d.new_value
        ]
        phones = extract_and_format_phones(texts_to_scan)

        # NOTE: State is NOT committed here. State is committed in commit_report()
        # only after Telegram message delivery succeeds!
        return ScheduleReport(
            manager=self.manager_name,
            date=today_str,
            diffs=diffs,
            phones=phones,
            full_schedule=all_slots,
            new_schedule=current_schedule,
        )

    async def get_current_schedule(self) -> tuple[str, str, list[ScheduleSlot], list[str]] | None:
        """Fetch today's current schedule snapshot on-demand without mutating internal state or diff engine.

        Returns:
            Tuple of (manager_name, today_date_str, slots, phones) or None if sheet/row is missing.
        """
        today_str = get_moscow_today_str(self.timezone)
        week_num = get_moscow_iso_week(self.timezone)

        sheet_names = await self.sheets_client.get_sheet_names(self.spreadsheet_id)
        target_sheet = self._find_target_sheet_name(sheet_names, week_num)
        if not target_sheet:
            _logger.warning("Sheet for week %d not found on-demand", week_num)
            return None

        rows = await self.sheets_client.get_sheet_values(self.spreadsheet_id, target_sheet)
        parsed = self._parse_sheet_data(rows, today_str)
        if parsed is None:
            return None

        current_schedule, all_slots = parsed
        phones = extract_and_format_phones(list(current_schedule.values()))

        return self.manager_name, today_str, all_slots, phones

