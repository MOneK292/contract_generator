"""Tests for Telegram contract generation handler."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from src.core.contract_engine import ContractResult
from src.interfaces.telegram.handlers.employee import (
    _combine_employee_text,
    _document_filename,
    _extract_last_name,
    _safe_filename,
    handle_employee_data,
    handle_missing_fields,
    process_action_change_template,
    process_action_start_over,
)
from src.interfaces.telegram.keyboards import (
    CHANGE_TEMPLATE_TEXT,
    START_OVER_TEXT,
)
from src.interfaces.telegram.states import ContractFlow, UserSessionStore
from src.services.config import TemplateCatalog


class TelegramGenerationTest(unittest.IsolatedAsyncioTestCase):
    """Telegram employee-data generation behavior."""

    async def test_successful_generation_sends_document_and_deletes_docx(self) -> None:
        with TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "contract.docx"
            docx_path.write_bytes(b"docx")
            engine = _FakeEngine(
                ContractResult(
                    success=True,
                    output_docx=docx_path,
                    output_pdf=None,
                    unresolved_placeholders=[],
                    execution_time=0.123,
                    used_template=None,
                    employee_fields_count=10,
                )
            )
            message = _FakeMessage("ФИО: Иванов Иван Иванович\nИНН: 123")
            state = _FakeState()
            sessions = self._ready_sessions()

            await handle_employee_data(
                message,
                state,
                self._catalog(),
                sessions,
                engine,
            )

            self.assertEqual(engine.calls, 1)
            self.assertEqual(engine.requests[0].project_id, "project-a")
            self.assertEqual(engine.requests[0].vacancy_id, "vacancy-1")
            self.assertEqual(engine.requests[0].template_id, "template-1")
            self.assertEqual(engine.requests[0].raw_employee_text, message.text)
            self.assertEqual(len(message.documents), 1)
            self.assertEqual(message.documents[0].filename, "Иванов_Vacancy_1.docx")
            self.assertFalse(docx_path.exists())
            self.assertEqual(state.state, ContractFlow.waiting_employee_data)
            self.assertTrue(any("успешно" in item.text for item in message.answers))
            self.assertFalse(any("<pre>" in item.text and "Ф:" in item.text for item in message.answers))

    async def test_successful_generation_sends_docx_then_pdf_and_deletes_both(self) -> None:
        with TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "contract.docx"
            pdf_path = Path(temp_dir) / "contract.pdf"
            docx_path.write_bytes(b"docx")
            pdf_path.write_bytes(b"pdf")
            engine = _FakeEngine(
                ContractResult(
                    success=True,
                    output_docx=docx_path,
                    output_pdf=pdf_path,
                    unresolved_placeholders=[],
                    execution_time=0.123,
                    used_template=None,
                    employee_fields_count=10,
                )
            )
            message = _FakeMessage("ФИО: Иванов Иван Иванович")

            await handle_employee_data(
                message,
                _FakeState(),
                self._catalog(),
                self._ready_sessions(),
                engine,
            )

            self.assertEqual([item.filename for item in message.documents], [
                "Иванов_Vacancy_1.docx",
                "Иванов_Vacancy_1.pdf",
            ])
            self.assertFalse(docx_path.exists())
            self.assertFalse(pdf_path.exists())

    async def test_engine_error_returns_clear_message_without_traceback(self) -> None:
        engine = _FakeEngine(
            ContractResult(
                success=False,
                output_docx=None,
                output_pdf=None,
                unresolved_placeholders=[],
                execution_time=0.1,
                used_template=None,
                employee_fields_count=0,
                error_message="renderer failed",
            )
        )
        message = _FakeMessage("ФИО: Иванов Иван Иванович")

        await handle_employee_data(
            message,
            _FakeState(),
            self._catalog(),
            self._ready_sessions(),
            engine,
        )

        self.assertEqual(len(message.documents), 0)
        self.assertTrue(any("Не удалось сформировать договор" in item.text for item in message.answers))
        self.assertTrue(any("renderer failed" in item.text for item in message.answers))
        self.assertFalse(any("Traceback" in item.text for item in message.answers))

    async def test_repeated_generation_uses_existing_selection(self) -> None:
        with TemporaryDirectory() as temp_dir:
            first_path = Path(temp_dir) / "first.docx"
            second_path = Path(temp_dir) / "second.docx"
            first_path.write_bytes(b"first")
            second_path.write_bytes(b"second")
            engine = _FakeEngine(
                ContractResult(
                    success=True,
                    output_docx=first_path,
                    output_pdf=None,
                    unresolved_placeholders=[],
                    execution_time=0.1,
                    used_template=None,
                    employee_fields_count=1,
                ),
                ContractResult(
                    success=True,
                    output_docx=second_path,
                    output_pdf=None,
                    unresolved_placeholders=[],
                    execution_time=0.2,
                    used_template=None,
                    employee_fields_count=1,
                ),
            )
            sessions = self._ready_sessions()

            await handle_employee_data(
                _FakeMessage("ФИО: Иванов Иван Иванович"),
                _FakeState(),
                self._catalog(),
                sessions,
                engine,
            )
            await handle_employee_data(
                _FakeMessage("ФИО: Петров Петр Петрович"),
                _FakeState(),
                self._catalog(),
                sessions,
                engine,
            )

            self.assertEqual(engine.calls, 2)
            self.assertEqual(engine.requests[0].template_id, "template-1")
            self.assertEqual(engine.requests[1].template_id, "template-1")

    async def test_unresolved_placeholders_start_missing_fields_wizard(self) -> None:
        with TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "incomplete.docx"
            docx_path.write_bytes(b"incomplete")
            engine = _FakeEngine(
                ContractResult(
                    success=True,
                    output_docx=docx_path,
                    output_pdf=None,
                    unresolved_placeholders=["Дата рождения", "Серия, номер П"],
                    execution_time=0.1,
                    used_template=None,
                    employee_fields_count=3,
                )
            )
            message = _FakeMessage("ФИО: Иванов Иван Иванович")
            state = _FakeState()
            sessions = self._ready_sessions()

            await handle_employee_data(message, state, self._catalog(), sessions, engine)

            self.assertEqual(len(message.documents), 0)
            self.assertEqual(state.state, ContractFlow.waiting_missing_fields)
            session = sessions.get(100)
            self.assertEqual(session.employee_text, "ФИО: Иванов Иван Иванович")
            self.assertEqual(session.missing_fields, ["Дата рождения", "Серия, номер П"])
            self.assertFalse(docx_path.exists())
            self.assertTrue(any("Дата рождения" in item.text for item in message.answers))

    async def test_missing_fields_retry_sends_document_after_success(self) -> None:
        with TemporaryDirectory() as temp_dir:
            incomplete_path = Path(temp_dir) / "incomplete.docx"
            complete_path = Path(temp_dir) / "complete.docx"
            incomplete_path.write_bytes(b"incomplete")
            complete_path.write_bytes(b"complete")
            engine = _FakeEngine(
                ContractResult(
                    success=True,
                    output_docx=incomplete_path,
                    output_pdf=None,
                    unresolved_placeholders=["Дата рождения"],
                    execution_time=0.1,
                    used_template=None,
                    employee_fields_count=3,
                ),
                ContractResult(
                    success=True,
                    output_docx=complete_path,
                    output_pdf=None,
                    unresolved_placeholders=[],
                    execution_time=0.2,
                    used_template=None,
                    employee_fields_count=4,
                ),
            )
            state = _FakeState()
            sessions = self._ready_sessions()

            await handle_employee_data(
                _FakeMessage("ФИО: Иванов Иван Иванович"),
                state,
                self._catalog(),
                sessions,
                engine,
            )
            retry_message = _FakeMessage("Дата рождения: 01.01.2000")
            await handle_missing_fields(
                retry_message,
                state,
                self._catalog(),
                sessions,
                engine,
            )

            self.assertEqual(engine.calls, 2)
            self.assertEqual(
                engine.requests[1].raw_employee_text,
                "ФИО: Иванов Иван Иванович\nДата рождения: 01.01.2000",
            )
            self.assertEqual(len(retry_message.documents), 1)
            self.assertEqual(state.state, ContractFlow.waiting_employee_data)
            self.assertEqual(sessions.get(100).employee_text, "")

    async def test_change_template_returns_to_template_selection(self) -> None:
        message = _FakeMessage("some text")
        callback = MagicMock()
        callback.from_user.id = 100
        callback.message = message
        callback.answer = AsyncMock()
        state = _FakeState()
        sessions = self._ready_sessions()

        await process_action_change_template(
            callback,
            state,
            self._catalog(),
            sessions,
        )

        self.assertEqual(state.state, ContractFlow.waiting_template)
        self.assertIsNone(sessions.get(100).template)
        self.assertTrue(any("Доступные шаблоны" in item.text for item in message.answers))
        self.assertIsNotNone(message.answers[-1].reply_markup)

    async def test_start_over_resets_session_and_returns_to_projects(self) -> None:
        message = _FakeMessage("some text")
        callback = MagicMock()
        callback.from_user.id = 100
        callback.message = message
        callback.answer = AsyncMock()
        state = _FakeState()
        sessions = self._ready_sessions()

        await process_action_start_over(
            callback,
            state,
            self._catalog(),
            sessions,
        )

        self.assertEqual(state.state, ContractFlow.waiting_project)
        session = sessions.get(100)
        self.assertIsNone(session.project)
        self.assertIsNone(session.vacancy)
        self.assertIsNone(session.template)
        self.assertTrue(any("Доступные проекты" in item.text for item in message.answers))

    def test_document_filename_falls_back_without_last_name(self) -> None:
        self.assertEqual(_document_filename("ИНН: 123", "Vacancy", ".docx"), "contract.docx")

    def _ready_sessions(self) -> UserSessionStore:
        sessions = UserSessionStore()
        session = sessions.get(100)
        session.project = "project-a"
        session.vacancy = "vacancy-1"
        session.template = "template-1"
        return sessions

    def _catalog(self) -> TemplateCatalog:
        return TemplateCatalog.from_mapping(
            {
                "projects": [
                    {
                        "id": "project-a",
                        "name": "Project A",
                        "vacancies": [
                            {
                                "id": "vacancy-1",
                                "name": "Vacancy 1",
                                "template_id": "template-1",
                                "template_ids": ["template-1", "template-2"],
                            }
                        ],
                    }
                ],
                "templates": [
                    {
                        "id": "template-1",
                        "name": "Contract.docx",
                        "google_drive_file_id": "drive-1",
                    },
                    {
                        "id": "template-2",
                        "name": "Addendum.docx",
                        "google_drive_file_id": "drive-2",
                    },
                ],
            }
        )


class _FakeEngine:
    def __init__(self, *results: ContractResult) -> None:
        self._results = list(results)
        self.calls = 0
        self.requests = []

    def generate(self, request):
        self.calls += 1
        self.requests.append(request)
        if self._results:
            return self._results.pop(0)
        return ContractResult(
            success=True,
            output_docx=None,
            output_pdf=None,
            unresolved_placeholders=[],
            execution_time=0,
            used_template=None,
            employee_fields_count=0,
        )


class _FakeState:
    def __init__(self) -> None:
        self.state = None

    async def set_state(self, state) -> None:
        self.state = state


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=100)
        self.answers: list[_FakeAnswer] = []
        self.documents = []

    async def answer(self, text: str, reply_markup=None, **kwargs):
        answer = _FakeAnswer(text=text, reply_markup=reply_markup, kwargs=kwargs)
        self.answers.append(answer)
        return answer

    async def answer_document(self, document) -> None:
        self.documents.append(document)


class _FakeAnswer:
    def __init__(self, text: str, reply_markup=None, kwargs=None) -> None:
        self.text = text
        self.reply_markup = reply_markup
        self.kwargs = kwargs or {}
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


if __name__ == "__main__":
    unittest.main()
