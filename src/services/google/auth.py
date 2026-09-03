"""Google Service Account authentication."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from src.core.exceptions import ContractGeneratorError
from src.services.config.settings_loader import AppConfig


class GoogleAuthError(ContractGeneratorError):
    """Raised when Google authentication cannot be initialized."""


@dataclass
class GoogleAuth:
    """Creates authorized Google API clients from service account config."""

    config: AppConfig
    scopes: tuple[str, ...] = ("https://www.googleapis.com/auth/drive.readonly",)
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )
    _drive_client: Any = field(default=None, init=False, repr=False)
    _sheets_client: Any = field(default=None, init=False, repr=False)

    def create_drive_client(self):
        """Create an authorized Google Drive v3 client."""
        if self._drive_client is not None:
            return self._drive_client

        drive_scopes = list(self.scopes)
        oauth_token = getattr(self.config.google, "oauth_refresh_token", "")
        oauth_client_id = getattr(self.config.google, "oauth_client_id", "")
        if oauth_token and oauth_client_id:
            try:
                from google.oauth2.credentials import Credentials as UserCredentials

                credentials = UserCredentials(
                    token=None,
                    refresh_token=oauth_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=oauth_client_id,
                    client_secret=getattr(self.config.google, "oauth_client_secret", ""),
                    scopes=drive_scopes,
                )
                client = build("drive", "v3", credentials=credentials, cache_discovery=False)
                self._logger.info("Google Drive client created via OAuth2 user credentials")
                self._drive_client = client
                return client
            except Exception as error:
                self._logger.exception("Failed to create Google Drive client from OAuth2 credentials")

        credentials_path = self.config.google.credentials_path
        try:
            credentials = Credentials.from_service_account_file(
                str(credentials_path),
                scopes=drive_scopes,
            )
            client = build("drive", "v3", credentials=credentials, cache_discovery=False)
        except Exception as error:
            self._logger.exception(
                "Failed to create Google Drive client from credentials: %s",
                credentials_path,
            )
            raise GoogleAuthError("Failed to create Google Drive client") from error

        self._logger.info("Google Drive client created")
        self._drive_client = client
        return client

    def create_sheets_client(self):
        """Create an authorized Google Sheets v4 client."""
        if self._sheets_client is not None:
            return self._sheets_client

        sheets_scopes = list(self.scopes)
        if "https://www.googleapis.com/auth/spreadsheets.readonly" not in sheets_scopes:
            sheets_scopes.append("https://www.googleapis.com/auth/spreadsheets.readonly")

        oauth_token = getattr(self.config.google, "oauth_refresh_token", "")
        oauth_client_id = getattr(self.config.google, "oauth_client_id", "")
        if oauth_token and oauth_client_id:
            try:
                from google.oauth2.credentials import Credentials as UserCredentials

                credentials = UserCredentials(
                    token=None,
                    refresh_token=oauth_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=oauth_client_id,
                    client_secret=getattr(self.config.google, "oauth_client_secret", ""),
                    scopes=sheets_scopes,
                )
                client = build("sheets", "v4", credentials=credentials, cache_discovery=False)
                self._logger.info("Google Sheets client created via OAuth2 user credentials")
                self._sheets_client = client
                return client
            except Exception as error:
                self._logger.exception("Failed to create Google Sheets client from OAuth2 credentials")
                raise GoogleAuthError("Failed to create Google Sheets client via OAuth2") from error

        credentials_path = self.config.google.credentials_path
        try:
            credentials = Credentials.from_service_account_file(
                str(credentials_path),
                scopes=sheets_scopes,
            )
            client = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        except Exception as error:
            self._logger.exception(
                "Failed to create Google Sheets client from credentials: %s",
                credentials_path,
            )
            raise GoogleAuthError("Failed to create Google Sheets client") from error

        self._logger.info("Google Sheets client created")
        self._sheets_client = client
        return client
