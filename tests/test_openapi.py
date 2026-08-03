"""A module containing various utility functions.

And constants for testing API client generation.

"""

from cilada.config import TestConfig as LoadTestConfig
from cilada.openapi import build_cases, merge_request_headers, required_global_headers

SPEC = {
    "openapi": "3.0.3",
    "paths": {
        "/patients/{patient_id}": {
            "get": {
                "operationId": "getPatient",
                "parameters": [
                    {
                        "name": "patient_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer", "minimum": 1},
                    },
                    {
                        "name": "X-Tenant",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
            },
            "delete": {"operationId": "deletePatient"},
        }
    },
}

COLLIDING_ENDPOINTS_SPEC = {
    "openapi": "3.0.3",
    "paths": {
        "/patients/{id}": {"get": {}},
        "/appointments/{id}": {"get": {}},
    },
}


def test_generates_only_enabled_methods() -> None:
    """Tests that the build_cases function generates test cases only for methods.

    Explicitly enabled in the LoadTestConfig.

    """
    cases = build_cases(
        SPEC, LoadTestConfig(enabled_methods=["GET"], cases_per_operation=2)
    )

    assert len(cases) == 2
    assert all(case.method == "GET" for case in cases)
    assert all(case.path == "/patients/1" for case in cases)
    assert all(case.name == "{patient_id}" for case in cases)


def test_discovers_required_headers() -> None:
    """Tests that the system correctly discovers.

    And identifies all necessary global HTTP headers.

    """
    headers = required_global_headers(SPEC, LoadTestConfig(enabled_methods=["GET"]))

    assert headers == {"X-Tenant"}


def test_configured_headers_override_generated_case_headers() -> None:
    """Tests that configured headers override generated case headers when merging.

    Request headers.

    """
    headers = merge_request_headers(
        {"Authorization": "Bearer real-token", "X-Tenant": "production"},
        {"Authorization": "test", "X-Tenant": "test", "X-Case": "value"},
    )

    assert headers == {
        "Authorization": "Bearer real-token",
        "X-Tenant": "production",
        "X-Case": "value",
    }


def test_header_merge_is_case_insensitive_and_excludes_skipped_headers() -> None:
    """Tests that merging request headers is case-insensitive.

    And correctly excludes headers marked as skipped.

    """
    headers = merge_request_headers(
        {"authorization": "Bearer configured"},
        {"Authorization": "test", "X-Tenant": "test"},
        {"x-tenant"},
    )

    assert headers == {"authorization": "Bearer configured"}


def test_disambiguates_endpoints_with_the_same_last_url_segment() -> None:
    """Tests that the system correctly disambiguates endpoints even when multiple.

    Endpoints share the same last URL segment.

    """
    cases = build_cases(
        COLLIDING_ENDPOINTS_SPEC,
        LoadTestConfig(enabled_methods=["GET"], cases_per_operation=1),
    )

    assert {case.name for case in cases} == {"patients/{id}", "appointments/{id}"}


def test_operation_parameters_override_path_parameters() -> None:
    """Tests that GET request parameters override path-level query parameters."""
    spec = {
        "openapi": "3.0.3",
        "paths": {
            "/patients": {
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"default": 10}}
                ],
                "get": {
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"default": 20},
                        }
                    ]
                },
            }
        },
    }

    cases = build_cases(
        spec, LoadTestConfig(enabled_methods=["GET"], cases_per_operation=1)
    )

    assert cases[0].params == {"limit": 20}
