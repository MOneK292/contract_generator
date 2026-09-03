"""Application settings loading."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

from src.core.exceptions import ConfigurationError
from src.services.config.template_catalog import TemplateCatalog


_ENV_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class GoogleConfig:
    """Google integration settings."""

    credentials_path: Path
    drive_root_folder_id: str
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_refresh_token: str = ""


@dataclass(frozen=True)
class LibreOfficeConfig:
    """LibreOffice conversion settings."""

    executable_path: Path | None
    timeout_seconds: int


@dataclass(frozen=True)
class PathsConfig:
    """Local project paths used by services."""

    root_dir: Path
    cache_dir: Path
    template_cache_dir: Path
    metadata_cache_dir: Path
    temp_dir: Path
    logs_dir: Path


@dataclass(frozen=True)
class LoggingConfig:
    """Logging settings."""

    level: str
    file_date_format: str


@dataclass(frozen=True)
class PdfConfig:
    """PDF generation cleanup settings."""

    delete_temp_docx: bool
    delete_temp_pdf_after_delivery: bool
    keep_temp_files_on_error: bool


@dataclass(frozen=True)
class ScheduleConfig:
    """Google Sheets schedule monitoring settings."""

    enabled: bool
    sheet_id: str
    manager_name: str
    poll_interval_seconds: int
    timezone: str
    notification_start_time: str
    notification_end_time: str


@dataclass(frozen=True)
class AuthConfig:
    """Telegram authorization settings."""

    authorized_users: tuple[int, ...]
    unauthorized_action: str = "ignore"


@dataclass(frozen=True)
class OffersConfig:
    """Google Sheets offers monitoring settings."""

    enabled: bool
    sheet_id: str
    poll_interval_seconds: int = 300
    samokat_sheet: str = ""
    lavka_sheet: str = ""


@dataclass(frozen=True)
class AppConfig:
    """Fully loaded application configuration."""

    root_dir: Path
    env: dict[str, str]
    google: GoogleConfig
    libreoffice: LibreOfficeConfig
    paths: PathsConfig
    logging: LoggingConfig
    pdf: PdfConfig
    schedule: ScheduleConfig
    auth: AuthConfig
    templates: TemplateCatalog
    offers: OffersConfig = OffersConfig(enabled=False, sheet_id="")


class SettingsLoader:
    """Loads `.env`, YAML settings, and template catalog."""

    def __init__(
        self,
        root_dir: str | Path | None = None,
        env_file: str | Path = ".env",
        settings_file: str | Path = "config/settings.yaml",
        templates_file: str | Path = "config/templates.yaml",
    ) -> None:
        self.root_dir = Path(root_dir or Path.cwd()).resolve()
        self.env_file = self._resolve(env_file)
        self.settings_file = self._resolve(settings_file)
        self.templates_file = self._resolve(templates_file)

    def load(self, *, validate_external_paths: bool = True) -> AppConfig:
        """Load application configuration and prepare local directories."""
        env = self._load_env()
        settings = self._load_yaml(self.settings_file)
        settings = self._expand_env(settings, env)

        paths = self._build_paths_config(self._required_mapping(settings, "paths"))
        self._ensure_directories(paths)

        config = AppConfig(
            root_dir=self.root_dir,
            env=env,
            google=self._build_google_config(self._required_mapping(settings, "google")),
            libreoffice=self._build_libreoffice_config(
                self._required_mapping(settings, "libreoffice")
            ),
            paths=paths,
            logging=self._build_logging_config(
                self._required_mapping(settings, "logging")
            ),
            pdf=self._build_pdf_config(self._required_mapping(settings, "pdf")),
            schedule=self._build_schedule_config(settings.get("schedule")),
            auth=self._build_auth_config(settings.get("auth")),
            templates=TemplateCatalog.from_file(self.templates_file),
            offers=self._build_offers_config(settings.get("offers")),
        )

        if validate_external_paths:
            self._validate_external_paths(config)

        return config

    def _load_env(self) -> dict[str, str]:
        file_values = dotenv_values(self.env_file) if self.env_file.exists() else {}
        env = dict(os.environ)
        env.update({
            key: value
            for key, value in file_values.items()
            if value is not None
        })
        return env

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise ConfigurationError(f"Configuration file does not exist: {path}")

        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}

        if not isinstance(data, dict):
            raise ConfigurationError(f"Configuration file must contain a mapping: {path}")

        return data

    def _expand_env(self, value: Any, env: dict[str, str]) -> Any:
        if isinstance(value, dict):
            return {key: self._expand_env(item, env) for key, item in value.items()}
        if isinstance(value, list):
            return [self._expand_env(item, env) for item in value]
        if isinstance(value, str):
            return _ENV_PATTERN.sub(lambda match: env.get(match.group("name"), ""), value)
        return value

    def _build_google_config(self, data: dict[str, Any]) -> GoogleConfig:
        return GoogleConfig(
            credentials_path=self._path(self._required_str(data, "credentials_path")),
            drive_root_folder_id=self._required_str(data, "drive_root_folder_id"),
            oauth_client_id=str(data.get("oauth_client_id", "") or "").strip(),
            oauth_client_secret=str(data.get("oauth_client_secret", "") or "").strip(),
            oauth_refresh_token=str(data.get("oauth_refresh_token", "") or "").strip(),
        )

    def _build_libreoffice_config(self, data: dict[str, Any]) -> LibreOfficeConfig:
        executable_path = self._optional_path(data.get("executable_path"))
        return LibreOfficeConfig(
            executable_path=executable_path,
            timeout_seconds=self._positive_int(data, "timeout_seconds"),
        )

    def _build_paths_config(self, data: dict[str, Any]) -> PathsConfig:
        return PathsConfig(
            root_dir=self.root_dir,
            cache_dir=self._path(self._required_str(data, "cache_dir")),
            template_cache_dir=self._path(self._required_str(data, "template_cache_dir")),
            metadata_cache_dir=self._path(self._required_str(data, "metadata_cache_dir")),
            temp_dir=self._path(self._required_str(data, "temp_dir")),
            logs_dir=self._path(self._required_str(data, "logs_dir")),
        )

    def _build_logging_config(self, data: dict[str, Any]) -> LoggingConfig:
        return LoggingConfig(
            level=self._required_str(data, "level").upper(),
            file_date_format=self._required_str(data, "file_date_format"),
        )

    def _build_pdf_config(self, data: dict[str, Any]) -> PdfConfig:
        return PdfConfig(
            delete_temp_docx=self._bool(data, "delete_temp_docx"),
            delete_temp_pdf_after_delivery=self._bool(
                data, "delete_temp_pdf_after_delivery"
            ),
            keep_temp_files_on_error=self._bool(data, "keep_temp_files_on_error"),
        )

    def _build_auth_config(self, data: dict[str, Any] | None) -> AuthConfig:
        data = data or {}
        raw_users = data.get("authorized_users")
        users: list[int] = []
        if isinstance(raw_users, (list, tuple)):
            for item in raw_users:
                try:
                    users.append(int(item))
                except (ValueError, TypeError):
                    continue
        elif isinstance(raw_users, str) and raw_users.strip():
            for item in raw_users.split(","):
                item_clean = item.strip()
                if item_clean.isdigit():
                    users.append(int(item_clean))
        elif isinstance(raw_users, int):
            users.append(raw_users)

        if not users:
            users = []

        unauthorized_action = str(data.get("unauthorized_action", "ignore")).strip().lower()
        if unauthorized_action not in ("ignore", "reply"):
            unauthorized_action = "ignore"

        return AuthConfig(
            authorized_users=tuple(users),
            unauthorized_action=unauthorized_action,
        )

    def _build_schedule_config(self, data: dict[str, Any] | None) -> ScheduleConfig:
        data = data or {}
        raw_enabled = data.get("enabled", True)
        if isinstance(raw_enabled, str):
            enabled = raw_enabled.lower() in ("true", "1", "yes", "on")
        else:
            enabled = bool(raw_enabled)

        poll_interval = data.get("poll_interval_seconds", 60)
        try:
            poll_interval_seconds = int(poll_interval)
        except (ValueError, TypeError):
            poll_interval_seconds = 60

        return ScheduleConfig(
            enabled=enabled,
            sheet_id=str(data.get("sheet_id", "")),
            manager_name=str(data.get("manager_name", "Manager")),
            poll_interval_seconds=max(5, poll_interval_seconds),
            timezone=str(data.get("timezone", "Europe/Moscow")),
            notification_start_time=str(data.get("notification_start_time", "09:00")),
            notification_end_time=str(data.get("notification_end_time", "20:00")),
        )

    def _build_offers_config(self, data: dict[str, Any] | None) -> OffersConfig:
        data = data or {}
        raw_enabled = data.get("enabled", True)
        if isinstance(raw_enabled, str):
            enabled = raw_enabled.lower() in ("true", "1", "yes", "on")
        else:
            enabled = bool(raw_enabled)

        poll_interval = data.get("poll_interval_seconds", 300)
        try:
            poll_interval_seconds = int(poll_interval)
        except (ValueError, TypeError):
            poll_interval_seconds = 300

        sheet_id = str(data.get("sheet_id", "")).strip()

        samokat_sheet = str(data.get("samokat_sheet", "")).strip()
        lavka_sheet = str(data.get("lavka_sheet", "")).strip()

        return OffersConfig(
            enabled=enabled,
            sheet_id=sheet_id,
            poll_interval_seconds=max(5, poll_interval_seconds),
            samokat_sheet=samokat_sheet,
            lavka_sheet=lavka_sheet,
        )

    def _ensure_directories(self, paths: PathsConfig) -> None:
        for directory in (
            paths.cache_dir,
            paths.template_cache_dir,
            paths.metadata_cache_dir,
            paths.temp_dir,
            paths.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def _validate_external_paths(self, config: AppConfig) -> None:
        self._validate_file(config.google.credentials_path, "Google credentials")

    def _validate_file(self, path: Path, label: str) -> None:
        if not path.exists():
            raise ConfigurationError(f"{label} path does not exist: {path}")
        if not path.is_file():
            raise ConfigurationError(f"{label} path is not a file: {path}")

    def _required_mapping(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        value = data.get(key)
        if not isinstance(value, dict):
            raise ConfigurationError(f"Missing or invalid configuration section: {key}")
        return value

    def _required_str(self, data: dict[str, Any], key: str) -> str:
        value = data.get(key)
        if value is None or str(value).strip() == "":
            raise ConfigurationError(f"Missing required configuration value: {key}")
        return str(value)

    def _positive_int(self, data: dict[str, Any], key: str) -> int:
        value = data.get(key)
        if not isinstance(value, int) or value <= 0:
            raise ConfigurationError(f"Configuration value must be a positive integer: {key}")
        return value

    def _bool(self, data: dict[str, Any], key: str) -> bool:
        value = data.get(key)
        if not isinstance(value, bool):
            raise ConfigurationError(f"Configuration value must be boolean: {key}")
        return value

    def _path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return (self.root_dir / path).resolve()

    def _optional_path(self, value: Any) -> Path | None:
        if value is None or str(value).strip() == "":
            return None
        return self._path(str(value))

    def _resolve(self, path: str | Path) -> Path:
        path = Path(path)
        if path.is_absolute():
            return path
        return (self.root_dir / path).resolve()
