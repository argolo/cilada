"""OpenAPI parsing and request case construction."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx

from cilada.config import ApiConfig, TestConfig


class OpenApiError(RuntimeError):
    """Raised when the OpenAPI contract cannot be fetched or interpreted."""


@dataclass(slots=True)
class RequestCase:
    """Executable case for a Locust user."""

    method: str
    path: str
    name: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    json_body: Any = None


def fetch_spec(config: ApiConfig) -> dict[str, Any]:
    """Baixa e valida superficialmente um documento OpenAPI JSON."""
    if not config.openapi_url:
        raise OpenApiError("The OpenAPI URL was not provided.")
    try:
        response = httpx.get(
            config.openapi_url,
            headers=config.headers,
            timeout=config.timeout_seconds,
            verify=config.verify_tls,
            follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise OpenApiError(f"Could not read {config.openapi_url}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
        raise OpenApiError(
            "The document does not contain a valid OpenAPI 'paths' object."
        )
    return data


def resolve_base_url(spec: dict[str, Any], config: ApiConfig) -> str:
    """Resolve target URL using configuration, servers, then schema URL precedence."""
    if config.base_url:
        return config.base_url.rstrip("/")
    servers = spec.get("servers", [])
    if servers and isinstance(servers[0], dict) and servers[0].get("url"):
        return str(servers[0]["url"]).rstrip("/")
    if config.openapi_url:
        return urljoin(config.openapi_url, "/").rstrip("/")
    raise OpenApiError("Could not determine the API base URL.")


def required_global_headers(spec: dict[str, Any], test: TestConfig) -> set[str]:
    """List required headers for selected operations."""
    result: set[str] = set()
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict) or not _path_selected(path, test):
            continue
        common = path_item.get("parameters", [])
        for method in test.enabled_methods:
            operation = path_item.get(method.lower())
            if not isinstance(operation, dict):
                continue
            for parameter in [*common, *operation.get("parameters", [])]:
                if (
                    isinstance(parameter, dict)
                    and parameter.get("in") == "header"
                    and parameter.get("required") is True
                    and parameter.get("name")
                ):
                    result.add(str(parameter["name"]))
    return result


def build_cases(spec: dict[str, Any], test: TestConfig) -> list[RequestCase]:
    """Convert OpenAPI operations into deterministic case variants."""
    cases_by_path: list[tuple[str, RequestCase]] = []
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict) or not _path_selected(path, test):
            continue
        common = path_item.get("parameters", [])
        for method in test.enabled_methods:
            operation = path_item.get(method.lower())
            if not isinstance(operation, dict):
                continue
            parameters = _merge_parameters(common, operation.get("parameters", []))
            for variant in range(test.cases_per_operation):
                cases_by_path.append(
                    (path, _make_case(path, method, operation, parameters, variant))
                )

    names = _unique_endpoint_names({path for path, _ in cases_by_path})
    for path, case in cases_by_path:
        case.name = names[path]
    return [case for _, case in cases_by_path]


def merge_request_headers(
    configured_headers: dict[str, str],
    case_headers: dict[str, str],
    excluded_headers: set[str] | None = None,
) -> dict[str, str]:
    """Merge headers case-insensitively while preserving configuration values."""
    excluded = {header.lower() for header in excluded_headers or set()}
    result: dict[str, tuple[str, str]] = {}
    for headers in (case_headers, configured_headers):
        for name, value in headers.items():
            if name.lower() not in excluded:
                result[name.lower()] = (name, value)
    return {name: value for name, value in result.values()}


def _unique_endpoint_names(paths: set[str]) -> dict[str, str]:
    """Use the shortest route suffix that distinguishes each endpoint."""
    result: dict[str, str] = {}
    path_parts = {
        path: tuple(part for part in path.split("/") if part) for path in paths
    }
    for path, parts in path_parts.items():
        for length in range(1, len(parts) + 1):
            suffix = "/".join(parts[-length:]) or "/"
            matches = sum(
                other_parts[-length:] == parts[-length:]
                for other_parts in path_parts.values()
            )
            if matches == 1:
                result[path] = suffix
                break
        else:
            result[path] = path or "/"
    return result


def _merge_parameters(common: Any, operation_parameters: Any) -> list[Any]:
    """Merge OpenAPI parameters with operation-level precedence."""
    merged: dict[tuple[str, str], Any] = {}
    unnamed: list[Any] = []
    for parameters in (common, operation_parameters):
        if not isinstance(parameters, list):
            continue
        for parameter in parameters:
            if not isinstance(parameter, dict):
                unnamed.append(parameter)
                continue
            name = parameter.get("name")
            location = parameter.get("in")
            if isinstance(name, str) and isinstance(location, str):
                merged[(name, location)] = parameter
            else:
                unnamed.append(parameter)
    return [*merged.values(), *unnamed]


def _path_selected(path: str, test: TestConfig) -> bool:
    """Checks if a given file path should be processed based on inclusion.

    And exclusion patterns defined in the TestConfig.

    Args:
        path: The absolute or relative path of the file to check.
        test: The configuration object containing lists of include and exclude path
        patterns.

    """
    included = not test.include_paths or any(
        fnmatch.fnmatch(path, pattern) for pattern in test.include_paths
    )
    excluded = any(fnmatch.fnmatch(path, pattern) for pattern in test.exclude_paths)
    return included and not excluded


def _make_case(
    path: str,
    method: str,
    operation: dict[str, Any],
    parameters: list[Any],
    variant: int,
) -> RequestCase:
    """Creates a request case object by constructing the path, headers.

    Query parameters, and body based on provided API specification details.

    Args:
        path: The base path string for the API endpoint.
        method: The HTTP method (e.g., 'GET', 'POST').
        operation: A dictionary containing operation-specific details, such as request
        body definitions.
        parameters: A list of parameter objects defining names, locations, and values.
        variant: An integer variant used for generating example values.

    """
    rendered_path = path
    headers: dict[str, str] = {}
    query: dict[str, Any] = {}
    for parameter in parameters:
        if not isinstance(parameter, dict) or "$ref" in parameter:
            continue
        required = bool(parameter.get("required"))
        if variant == 1 and not required:
            continue
        name = str(parameter.get("name", "parameter"))
        value = _example(parameter.get("schema", {}), variant, parameter.get("example"))
        location = parameter.get("in")
        if location == "path":
            rendered_path = rendered_path.replace("{" + name + "}", str(value))
        elif location == "query":
            query[name] = value
        elif location == "header":
            headers[name] = str(value)

    body = None
    request_body = operation.get("requestBody", {})
    if isinstance(request_body, dict):
        media = request_body.get("content", {}).get("application/json", {})
        if isinstance(media, dict):
            body = _example(media.get("schema", {}), variant, media.get("example"))

    return RequestCase(
        method=method,
        path=rendered_path,
        name="",
        headers=headers,
        params=query,
        json_body=body,
    )


def _example(schema: Any, variant: int, explicit: Any = None) -> Any:
    """Generates an example value based on a JSON schema.

    Considering specified variants and explicit overrides.

    Args:
        schema: The JSON schema object used to determine the structure of the example.
        variant: An integer used to select different possible values or paths within the
        schema (e.g., for enums or number ranges).
        explicit: An optional value that, if provided, is returned immediately,
        overriding all other logic.

    """
    if explicit is not None:
        return explicit
    if not isinstance(schema, dict):
        return "test"
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][variant % len(schema["enum"])]
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        required = set(schema.get("required", []))
        return {
            name: _example(child, variant)
            for name, child in schema.get("properties", {}).items()
            if variant != 1 or name in required
        }
    if schema_type == "array":
        return [_example(schema.get("items", {}), variant)]
    if schema_type in {"integer", "number"}:
        return schema.get("minimum", 1) if variant != 2 else schema.get("maximum", 100)
    if schema_type == "boolean":
        return variant % 2 == 0
    if schema.get("format") == "date":
        return "2026-01-01"
    if schema.get("format") == "date-time":
        return "2026-01-01T00:00:00Z"
    return "test" if variant != 2 else "x" * min(int(schema.get("maxLength", 64)), 64)
