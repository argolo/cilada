"""Cilada configuration loading and validation."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")
HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}
)


class ConfigurationError(ValueError):
    """Raised when configuration is invalid or incomplete."""


@dataclass(slots=True)
class ApiConfig:
    """API connection settings."""

    openapi_url: str | None = None
    base_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    verify_tls: bool = True
    timeout_seconds: float = 30.0


@dataclass(slots=True)
class TestConfig:
    """Case selection and generation policy."""

    enabled_methods: list[str] = field(
        default_factory=lambda: ["GET", "HEAD", "OPTIONS"]
    )
    include_paths: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    cases_per_operation: int = 3
    failure_status_classes: list[int] = field(default_factory=lambda: [5])


@dataclass(slots=True)
class LocustConfig:
    """Basic Locust execution settings."""

    users: int = 10
    spawn_rate: float = 2.0
    run_time: str = "1m"
    headless: bool = True
    web_host: str = "127.0.0.1"
    web_port: int = 8089
    csv_prefix: str | None = None
    html_report: str | None = None


@dataclass(slots=True)
class Settings:
    """Consolidated application configuration."""

    api: ApiConfig = field(default_factory=ApiConfig)
    test: TestConfig = field(default_factory=TestConfig)
    locust: LocustConfig = field(default_factory=LocustConfig)


def _expand_env(value: str) -> str:
    """Expands environment variables within a string using the pattern defined by.

    ENV_PATTERN.

    Args:
        value: The input string containing potential environment variable placeholders.

    """

    def replace(match: re.Match[str]) -> str:
        """Replaces a match object with the value of an environment variable.

        Args:
            match: The regex match object containing the captured group name of the
            required environment variable.

        """
        name = match.group(1)
        if name not in os.environ:
            raise ConfigurationError(
                f"Required environment variable {name!r} is not set."
            )
        return os.environ[name]

    return ENV_PATTERN.sub(replace, value)


def _string_map(value: Any, section: str) -> dict[str, str]:
    """Maps all string values within a dictionary (TOML table) to environment-expanded.

    Strings.

    Args:
        value: The dictionary containing the key-value pairs to be mapped.
        section: The name of the section being processed.

    """
    if not isinstance(value, dict):
        raise ConfigurationError(f"{section} must be a TOML table.")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ConfigurationError(f"All {section} values must be strings.")
        result[key] = _expand_env(item)
    return result


def _optional_string(value: Any, field_name: str) -> str | None:
    """Returns the provided value if it is a non-None string; otherwise, returns None.

    Args:
        value: The input value to check and return.
        field_name: The name of the field associated with the value, used for error
        messages.

    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{field_name} must be a string.")
    return value


def _string_list(value: Any, field_name: str) -> list[str]:
    """Validates and returns a list of strings.

    Args:
        value: The input value, expected to be a list of strings.
        field_name: The name of the field being validated.

    """
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigurationError(f"{field_name} must be a list of strings.")
    return value


def _integer(value: Any, field_name: str) -> int:
    """Ensures that the provided value is an integer.

    And raises a ConfigurationError if it is not.

    Args:
        value: The value to check and convert to an integer.
        field_name: The name of the field associated with the value, used in error
        messages.

    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{field_name} must be an integer.")
    return int(value)


def _status_classes(value: Any) -> list[int]:
    """Returns a list of integers representing status classes.

    After validating that the input is a non-empty list containing only integers between
    1 and 5.

    Args:
        value: The list of integer status classes to be returned.

    """
    if not isinstance(value, list) or not all(
        not isinstance(item, bool) and isinstance(item, int) for item in value
    ):
        raise ConfigurationError(
            "test.failure_status_classes must be a list of integers between 1 and 5."
        )
    if not value or any(item not in {1, 2, 3, 4, 5} for item in value):
        raise ConfigurationError(
            "test.failure_status_classes must contain classes between 1 and 5."
        )
    return value


def should_mark_failure(status_code: int, failure_status_classes: list[int]) -> bool:
    """Return whether a response belongs to a configured failure class."""
    return status_code // 100 in failure_status_classes


def _number(value: Any, field_name: str) -> float:
    """Converts a given value to a float, ensuring it is numeric.

    Args:
        value: The input value to be converted to a float.
        field_name: The name of the field associated with the value, used for error
        reporting.

    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{field_name} must be numeric.")
    return float(value)


def _boolean(value: Any, field_name: str) -> bool:
    """Checks if a given value is a boolean and raises an error otherwise.

    Args:
        value: The boolean value to check.
        field_name: The name of the field associated with the value.

    """
    if not isinstance(value, bool):
        raise ConfigurationError(f"{field_name} must be true or false.")
    return value


def load_settings(path: Path = Path(".cilada.toml")) -> Settings:
    """Read a TOML file and return typed settings."""
    if not path.exists():
        if path.name == ".cilada.toml":
            return Settings()
        raise ConfigurationError(f"Configuration file {path} not found.")

    try:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        message = f"Could not read {path}: invalid TOML."
        raise ConfigurationError(message) from exc

    api_raw = raw.get("api", {})
    test_raw = raw.get("test", {})
    locust_raw = raw.get("locust", {})
    if not all(isinstance(item, dict) for item in (api_raw, test_raw, locust_raw)):
        raise ConfigurationError("api, test, and locust sections must be TOML tables.")

    methods = [
        item.upper()
        for item in _string_list(
            test_raw.get("enabled_methods", []), "test.enabled_methods"
        )
    ]
    invalid = sorted(set(methods) - HTTP_METHODS)
    if invalid:
        raise ConfigurationError(f"Invalid HTTP methods: {', '.join(invalid)}.")

    settings = Settings(
        api=ApiConfig(
            openapi_url=_optional_string(api_raw.get("openapi_url"), "api.openapi_url"),
            base_url=_optional_string(api_raw.get("base_url"), "api.base_url"),
            headers=_string_map(api_raw.get("headers", {}), "api.headers"),
            verify_tls=_boolean(api_raw.get("verify_tls", True), "api.verify_tls"),
            timeout_seconds=_number(
                api_raw.get("timeout_seconds", 30.0), "api.timeout_seconds"
            ),
        ),
        test=TestConfig(
            enabled_methods=methods or ["GET", "HEAD", "OPTIONS"],
            include_paths=_string_list(
                test_raw.get("include_paths", []), "test.include_paths"
            ),
            exclude_paths=_string_list(
                test_raw.get("exclude_paths", []), "test.exclude_paths"
            ),
            cases_per_operation=_integer(
                test_raw.get("cases_per_operation", 3), "test.cases_per_operation"
            ),
            failure_status_classes=_status_classes(
                test_raw.get("failure_status_classes", [5])
            ),
        ),
        locust=LocustConfig(
            users=_integer(locust_raw.get("users", 10), "locust.users"),
            spawn_rate=_number(locust_raw.get("spawn_rate", 2.0), "locust.spawn_rate"),
            run_time=(
                _optional_string(locust_raw.get("run_time", "1m"), "locust.run_time")
                or ""
            ),
            headless=_boolean(locust_raw.get("headless", True), "locust.headless"),
            web_host=(
                _optional_string(
                    locust_raw.get("web_host", "127.0.0.1"), "locust.web_host"
                )
                or ""
            ),
            web_port=_integer(locust_raw.get("web_port", 8089), "locust.web_port"),
            csv_prefix=_optional_string(
                locust_raw.get("csv_prefix"), "locust.csv_prefix"
            ),
            html_report=_optional_string(
                locust_raw.get("html_report"), "locust.html_report"
            ),
        ),
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    """Validate bounds that prevent ambiguous executions."""
    if settings.locust.users < 1:
        raise ConfigurationError("locust.users must be greater than zero.")
    if settings.locust.spawn_rate <= 0:
        raise ConfigurationError("locust.spawn_rate must be greater than zero.")
    if settings.api.timeout_seconds <= 0:
        raise ConfigurationError("api.timeout_seconds must be greater than zero.")
    if settings.test.cases_per_operation < 1:
        raise ConfigurationError("test.cases_per_operation must be greater than zero.")
    if not settings.locust.run_time:
        raise ConfigurationError("locust.run_time cannot be empty.")
    if not settings.locust.web_host:
        raise ConfigurationError("locust.web_host cannot be empty.")
    if not 1 <= settings.locust.web_port <= 65535:
        raise ConfigurationError("locust.web_port must be between 1 and 65535.")
    for value, field_name in (
        (settings.api.openapi_url, "api.openapi_url"),
        (settings.api.base_url, "api.base_url"),
    ):
        if value is not None:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ConfigurationError(f"{field_name} must be a valid HTTP(S) URL.")
    for value, field_name in (
        (settings.locust.csv_prefix, "locust.csv_prefix"),
        (settings.locust.html_report, "locust.html_report"),
    ):
        if value is not None and not value.strip():
            raise ConfigurationError(f"{field_name} cannot be empty.")
