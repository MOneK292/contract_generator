"""Comprehensive unit tests for Schedule Tracker service, SQLite persistence, delivery guarantees, retries, on-demand query, authorization middleware, and formatting."""

import asyncio
from datetime import datetime
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
import httplib2
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import Message, User, Chat

from src.interfaces.telegram.middlewares.auth import AuthorizationMiddleware
from src.interfaces.telegram.handlers.schedule import handle_schedule_command
from src.services.schedule_tracker.models import (
    ChangeType,
    ScheduleDiff,
    ScheduleReport,
    ScheduleSlot,
)
from src.services.schedule_tracker.time_utils import (
    clean_cell_text,
    get_moscow_iso_week,
    get_moscow_today_str,
    is_within_time_window,
    parse_time_slot,
)
from src.services.schedule_tracker.phone_extractor import extract_and_format_phones
from src.services.schedule_tracker.message_formatter import (
    format_current_schedule_message,
    format_schedule_message,
)
from src.services.schedule_tracker.repository import ScheduleRepository
from src.services.schedule_tracker.sheets_client import GoogleSheetsClient
from src.services.schedule_tracker.tracker_service import ScheduleTrackerService
from src.services.schedule_tracker.poller import SchedulePoller


def test_parse_time_slot_decimal():
    assert parse_time_slot(0.4166666666666667) == "10:00"
    assert parse_time_slot(0.6041666666666666) == "14:30"
    assert parse_time_slot(0.7916666666666666) == "19:00"
    assert parse_time_slot(0.375) is None
    assert parse_time_slot(0.833333) is None


def test_parse_time_slot_strings():
    assert parse_time_slot("10:00") == "10:00"
    assert parse_time_slot("14.30") == "14:30"
    assert parse_time_slot("18:45:00") == "18:45"
    assert parse_time_slot("09:00") is None
    assert parse_time_slot("21:00") is None
    assert parse_time_slot("invalid") is None
    assert parse_time_slot(None) is None


def test_clean_cell_text():
    assert clean_cell_text("  hello \r\n world  ") == "hello \n world"
    assert clean_cell_text(None) == ""
    assert clean_cell_text(123) == "123"


def test_phone_extractor():
    texts = [
        "Иван +7 (999) 123-45-67 созвон",
        "89991234567 повтор того же номера",
        "Петр 79123456789 и Анна 8-900-555-44-33",
        "Без номера встреча",
    ]
    phones = extract_and_format_phones(texts)
    assert phones == [
        "+79991234567",
        "+79123456789",
        "+79005554433",
    ]


def test_format_schedule_message():
    diffs = [
        ScheduleDiff(
            time="11:00",
            old_value=None,
            new_value="Иван +7 (999) 111-22-33",
            change_type=ChangeType.NEW,
        ),
        ScheduleDiff(
            time="14:00",
            old_value="Старая встреча",
            new_value=None,
            change_type=ChangeType.DELETED,
        ),
    ]
    full = [
        ScheduleSlot(time="11:00", value="Иван +7 (999) 111-22-33"),
        ScheduleSlot(time="15:00", value="Совещание"),
    ]
    report = ScheduleReport(
        manager="Зорина Юлия",
        date="05.08.2026",
        diffs=diffs,
        phones=["+79991112233"],
        full_schedule=full,
        new_schedule={"11:00": "Иван +7 (999) 111-22-33", "15:00": "Совещание"},
    )
    msg = format_schedule_message(report)
    assert "Зорина Юлия" in msg
    assert "05.08.2026" in msg
    assert "<b>11:00:</b> Иван +7 (999) 111-22-33" in msg
    assert "<b>14:00:</b> <i>[Удалено: Старая встреча]</i>" in msg
    assert "<code>+79991112233</code>" in msg
    assert "<blockquote expandable>" in msg


def test_format_current_schedule_message():
    slots = [
        ScheduleSlot(time="10:00", value="Иван +7 (999) 111-22-33"),
        ScheduleSlot(time="14:30", value="Обед / перерыв"),
    ]
    phones = ["+79991112233"]
    msg = format_current_schedule_message(
        manager="Зорина Юлия",
        date="05.08.2026",
        slots=slots,
        phones=phones,
    )
    assert "Актуальное расписание на сегодня" in msg
    assert "Зорина Юлия" in msg
    assert "05.08.2026" in msg
    assert "<code>+79991112233</code>" in msg
    assert "<b>10:00:</b> Иван +7 (999) 111-22-33" in msg
    assert "<blockquote expandable>" in msg


def test_is_within_time_window():
    # Inside 09:00 - 20:00
    t_inside = datetime.strptime("14:30", "%H:%M")
    assert is_within_time_window("09:00", "20:00", current_time=t_inside) is True

    # Exactly at boundaries
    t_start = datetime.strptime("09:00", "%H:%M")
    t_end = datetime.strptime("20:00", "%H:%M")
    assert is_within_time_window("09:00", "20:00", current_time=t_start) is True
    assert is_within_time_window("09:00", "20:00", current_time=t_end) is True

    # Outside boundaries
    t_early = datetime.strptime("08:59", "%H:%M")
    t_late = datetime.strptime("20:01", "%H:%M")
    assert is_within_time_window("09:00", "20:00", current_time=t_early) is False
    assert is_within_time_window("09:00", "20:00", current_time=t_late) is False


def test_sqlite_repository_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_schedule.db"
        repo = ScheduleRepository(db_path)

        # 1. Initial empty load
        assert repo._sync_load_schedule("Зорина Юлия", "05.08.2026") == {}

        # 2. Save schedule
        initial_data = {"10:00": "Клиент 1", "14:00": "Клиент 2"}
        repo._sync_save_schedule("Зорина Юлия", "05.08.2026", initial_data)

        # 3. Load saved schedule
        loaded = repo._sync_load_schedule("Зорина Юлия", "05.08.2026")
        assert loaded == initial_data

        # 4. Check different manager or date is isolated
        assert repo._sync_load_schedule("Другой Менеджер", "05.08.2026") == {}
        assert repo._sync_load_schedule("Зорина Юлия", "06.08.2026") == {}

        # 5. Overwrite / update schedule
        updated_data = {"10:00": "Клиент 1 изменен", "15:00": "Новый клиент"}
        repo._sync_save_schedule("Зорина Юлия", "05.08.2026", updated_data)
        assert repo._sync_load_schedule("Зорина Юлия", "05.08.2026") == updated_data


def test_sqlite_state_restoration_on_restart():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_schedule.db"
            repo = ScheduleRepository(db_path)

            today = get_moscow_today_str("Europe/Moscow")
            week = get_moscow_iso_week("Europe/Moscow")
            sheet_name = f"Неделя {week}"

            mock_client = MagicMock()
            mock_client.get_sheet_names = AsyncMock(return_value=[sheet_name])

            # Pre-populate database (as if previous run saved state)
            saved_state = {"10:00": "Ранее сохраненная запись", "14:00": "Встреча"}
            await repo.save_schedule("Зорина Юлия", today, saved_state)

            # Start fresh tracker service instance (simulating bot restart)
            tracker = ScheduleTrackerService(
                sheets_client=mock_client,
                spreadsheet_id="test_sheet_id",
                manager_name="Зорина Юлия",
                repository=repo,
            )

            # Sheet has the exact same data
            rows = [
                ["Дата", "Менеджер", "10:00", "14:00"],
                [today, "Зорина Юлия", "Ранее сохраненная запись", "Встреча"],
            ]
            mock_client.get_sheet_values = AsyncMock(return_value=rows)

            # Check for updates: because state was restored from SQLite, no false alarm/no diffs!
            report = await tracker.check_for_updates()
            assert report is None

            # Now modify sheet in row
            updated_rows = [
                ["Дата", "Менеджер", "10:00", "14:00"],
                [today, "Зорина Юлия", "Ранее сохраненная запись", "Новая встреча +79991234567"],
            ]
            mock_client.get_sheet_values = AsyncMock(return_value=updated_rows)

            # Diff should be detected against the SQLite-restored baseline
            report = await tracker.check_for_updates()
            assert report is not None
            assert len(report.diffs) == 1
            assert report.diffs[0].time == "14:00"
            assert report.diffs[0].change_type == ChangeType.MODIFIED
            assert report.diffs[0].old_value == "Встреча"
            assert report.diffs[0].new_value == "Новая встреча +79991234567"

    asyncio.run(_run())


def test_get_current_schedule_does_not_mutate_state():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_schedule.db"
            repo = ScheduleRepository(db_path)

            today = get_moscow_today_str("Europe/Moscow")
            week = get_moscow_iso_week("Europe/Moscow")
            sheet_name = f"Неделя {week}"

            mock_client = MagicMock()
            mock_client.get_sheet_names = AsyncMock(return_value=[sheet_name])

            rows = [
                ["Дата", "Менеджер", "10:00", "15:00"],
                [today, "Зорина Юлия", "Иван +79991234567", "Встреча"],
            ]
            mock_client.get_sheet_values = AsyncMock(return_value=rows)

            tracker = ScheduleTrackerService(
                sheets_client=mock_client,
                spreadsheet_id="test_sheet_id",
                manager_name="Зорина Юлия",
                repository=repo,
            )

            # Query current schedule on-demand
            res = await tracker.get_current_schedule()
            assert res is not None
            manager, date_str, slots, phones = res
            assert manager == "Зорина Юлия"
            assert date_str == today
            assert len(slots) == 2
            assert "+79991234567" in phones

            # Tracker internal state MUST remain uninitialized / not mutated
            assert tracker._last_schedule is None
            assert tracker._last_date is None
            assert await repo.load_schedule("Зорина Юлия", today) == {}

    asyncio.run(_run())


def test_state_committed_only_after_successful_send():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_schedule.db"
            repo = ScheduleRepository(db_path)

            today = get_moscow_today_str("Europe/Moscow")
            week = get_moscow_iso_week("Europe/Moscow")
            sheet_name = f"Неделя {week}"

            mock_client = MagicMock()
            mock_client.get_sheet_names = AsyncMock(return_value=[sheet_name])

            # Initial baseline
            initial_rows = [
                ["Дата", "Менеджер", "10:00"],
                [today, "Зорина Юлия", "Слот 1"],
            ]
            mock_client.get_sheet_values = AsyncMock(return_value=initial_rows)

            tracker = ScheduleTrackerService(
                sheets_client=mock_client,
                spreadsheet_id="test_sheet_id",
                manager_name="Зорина Юлия",
                repository=repo,
            )
            # Cold start baseline
            assert await tracker.check_for_updates() is None

            # Sheet changes
            changed_rows = [
                ["Дата", "Менеджер", "10:00"],
                [today, "Зорина Юлия", "Слот 1 изменен"],
            ]
            mock_client.get_sheet_values = AsyncMock(return_value=changed_rows)

            mock_bot = MagicMock()
            # 1. Telegram delivery FAILS
            mock_bot.send_message = AsyncMock(side_effect=Exception("Telegram connection lost"))

            poller = SchedulePoller(
                bot=mock_bot,
                tracker=tracker,
                recipients=[123456, 789012],
                max_telegram_retries=1,
            )

            await poller._poll_iteration()

            # State in SQLite and memory MUST NOT be committed because sending failed!
            loaded_db = await repo.load_schedule("Зорина Юлия", today)
            assert loaded_db.get("10:00") == "Слот 1"  # Old state preserved in DB

            # 2. Telegram delivery SUCCEEDS on retry
            mock_bot.send_message = AsyncMock(return_value=True)

            # Reset memory state to simulate that tracker should still detect diff from DB
            # or we just re-instantiate tracker if it's purely memory-based.
            tracker._last_schedule = None  # Force re-check
            
            await poller._poll_iteration()

            # Now state MUST be committed in DB
            loaded_db_after = await repo.load_schedule("Зорина Юлия", today)
            assert loaded_db_after.get("10:00") == "Слот 1 изменен"

    asyncio.run(_run())


def test_authorization_middleware():
    async def _run():
        auth = AuthorizationMiddleware(
            authorized_users=[111111111, 222222222],
            unauthorized_action="reply",
        )

        handler_called = False

        async def dummy_handler(event, data):
            nonlocal handler_called
            handler_called = True
            return "ok"

        # 1. Authorized user
        user_ok = User(id=111111111, is_bot=False, first_name="Authorized")
        event_ok = MagicMock(spec=Message)
        event_ok.from_user = user_ok
        event_ok.answer = AsyncMock()

        handler_called = False
        res = await auth(dummy_handler, event_ok, {"event_from_user": user_ok})
        assert res == "ok"
        assert handler_called is True
        event_ok.answer.assert_not_called()

        # 2. Unauthorized user
        user_denied = User(id=999999999, is_bot=False, first_name="Intruder")
        event_denied = MagicMock(spec=Message)
        event_denied.from_user = user_denied
        event_denied.answer = AsyncMock()

        handler_called = False
        res_denied = await auth(dummy_handler, event_denied, {"event_from_user": user_denied})
        assert res_denied is None
        assert handler_called is False
        event_denied.answer.assert_called_once()

    asyncio.run(_run())


def test_schedule_handler_command():
    async def _run():
        mock_tracker = MagicMock()
        mock_tracker.get_current_schedule = AsyncMock(
            return_value=(
                "Зорина Юлия",
                "05.08.2026",
                [ScheduleSlot(time="10:00", value="Иван +79991234567")],
                ["+79991234567"],
            )
        )

        mock_message = MagicMock(spec=Message)
        mock_message.chat = MagicMock(id=123)
        mock_message.answer = AsyncMock()
        mock_message.bot = MagicMock()
        mock_message.bot.send_chat_action = AsyncMock()

        await handle_schedule_command(mock_message, schedule_tracker=mock_tracker)

        assert mock_message.answer.call_count == 1
        answer_text = mock_message.answer.call_args[0][0]
        assert "Актуальное расписание на сегодня" in answer_text
        assert "Зорина Юлия" in answer_text
        assert "+79991234567" in answer_text

    asyncio.run(_run())


def test_google_sheets_client_retry_and_client_reuse():
    credentials_path = Path("config/credentials.json")
    client = GoogleSheetsClient(credentials_path, max_retries=2, base_backoff_seconds=0.01)

    call_count = 0

    def transient_failure_then_success():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            resp = httplib2.Response({"status": 503})
            raise HttpError(resp, b"Service Unavailable")
        return ["Sheet1"]

    result = client._execute_with_retry("test_action", transient_failure_then_success)
    assert result == ["Sheet1"]
    assert call_count == 2


def test_single_poller_lock_prevents_overlap():
    async def _run():
        mock_bot = MagicMock()
        mock_tracker = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_settings = AsyncMock(return_value={"enabled": True})
        mock_tracker.repository = mock_repo

        # Simulate slow check_for_updates
        async def slow_check():
            await asyncio.sleep(0.05)
            return None

        mock_tracker.check_for_updates = AsyncMock(side_effect=slow_check)
        mock_tracker.timezone = "Europe/Moscow"

        poller = SchedulePoller(
            bot=mock_bot,
            tracker=mock_tracker,
            recipients=[123456],
        )

        # Launch two simultaneous iterations
        task1 = asyncio.create_task(poller._poll_iteration())
        task2 = asyncio.create_task(poller._poll_iteration())
        await asyncio.gather(task1, task2)

        # Because lock prevented overlapping second call, check_for_updates was executed once
        assert mock_tracker.check_for_updates.call_count == 1

    asyncio.run(_run())


def test_telegram_retry_after_handling():
    async def _run():
        mock_bot = MagicMock()
        mock_tracker = MagicMock()

        # First call raises TelegramRetryAfter, second call succeeds
        call_count = 0

        async def send_msg(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TelegramRetryAfter(
                    method=MagicMock(),
                    message="Too Many Requests: retry after 0",
                    retry_after=0,
                )
            return True

        mock_bot.send_message = AsyncMock(side_effect=send_msg)

        poller = SchedulePoller(
            bot=mock_bot,
            tracker=mock_tracker,
            recipients=[123456],
            max_telegram_retries=2,
        )

        success = await poller._send_notification_to_recipient("Test message", 123456)
        assert success is True
        assert call_count == 2

    asyncio.run(_run())


def test_repository_cleanup_old_records():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_schedule.db"
        repo = ScheduleRepository(db_path)

        # Insert a current record
        repo._sync_save_schedule("Зорина Юлия", "05.08.2026", {"10:00": "Свежая запись"})
        assert len(repo._sync_load_schedule("Зорина Юлия", "05.08.2026")) == 1

        # Cleanup with 30 days keeps current records
        deleted = repo._sync_cleanup_old_records(days_to_keep=30)
        assert deleted == 0
        assert len(repo._sync_load_schedule("Зорина Юлия", "05.08.2026")) == 1
