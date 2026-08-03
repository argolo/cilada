"""The module contains various unit tests for the cilada CLI application.

Covering functionality like header handling, configuration loading, summary aggregation,
and status code metric reporting.

"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from cilada.cli import (
    BANNER,
    StatusCodeSummary,
    _ask_missing_headers,
    _load_status_codes,
    _load_summary,
    app,
)
from cilada.config import Settings, load_settings


def test_missing_header_can_be_skipped_after_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests that missing headers can be skipped after confirmation.

    Args:
        monkeypatch: A pytest MonkeyPatch object used to temporarily modify modules or
        classes.

    """
    confirmations = iter([False, True])
    monkeypatch.setattr(typer, "confirm", lambda *args, **kwargs: next(confirmations))
    monkeypatch.setattr(
        typer,
        "prompt",
        lambda *args, **kwargs: pytest.fail("must not request a value"),
    )

    _ask_missing_headers(Settings(), {"X-Tenant"}, interactive=True)


def test_non_interactive_confirms_running_without_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests that the application correctly handles missing headers when running in a.

    Non-interactive environment, ensuring confirmation prompts are bypassed and value
    requests fail.

    Args:
        monkeypatch: A pytest fixture used to temporarily modify attributes or methods
        on modules or classes during testing.

    """
    monkeypatch.setattr(typer, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        typer,
        "prompt",
        lambda *args, **kwargs: pytest.fail("must not request values"),
    )

    _ask_missing_headers(Settings(), {"X-Tenant"}, interactive=False)


def test_missing_header_aborts_when_execution_is_not_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests that the application aborts when required headers are missing if.

    Execution confirmation is not requested.

    Args:
        monkeypatch: A pytest fixture used to temporarily modify attributes or methods
        on modules.

    """
    monkeypatch.setattr(typer, "confirm", lambda *args, **kwargs: False)

    with pytest.raises(typer.Exit) as error:
        _ask_missing_headers(Settings(), {"X-Tenant"}, interactive=False)

    assert error.value.exit_code == 2


def test_banner_has_truck_emoji() -> None:
    """Asserts that the global variable BANNER contains a truck emoji."""
    assert BANNER == "É uma cilada, Bino! 🚚"


def test_non_interactive_help_describes_header_confirmation() -> None:
    """Tests that the help output for a non-interactive run correctly describes header.

    Confirmation.

    """
    result = CliRunner().invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "Do not request values" in result.output
    assert "required headers" in result.output


def test_config_init_creates_a_valid_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests that running the 'config init' command creates a valid configuration.

    Template file.

    Args:
        tmp_path: A temporary path object used for creating and managing test files and
        directories.
        monkeypatch: A pytest fixture used to temporarily modify or patch attributes,
        functions, or classes during testing.

    """
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["config", "init"])

    config = tmp_path / ".cilada.toml"
    assert result.exit_code == 0
    assert config.exists()
    assert "failure_status_classes = [5]" in config.read_text(encoding="utf-8")
    assert load_settings(config).locust.users == 10


def test_config_init_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    """Tests that the 'config init' command does not overwrite an existing.

    Configuration file.

    Args:
        tmp_path: A temporary path object used for creating and managing test files.

    """
    config = tmp_path / ".cilada.toml"
    config.write_text("existing configuration", encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "init", "--path", str(config)])

    assert result.exit_code == 2
    assert config.read_text(encoding="utf-8") == "existing configuration"


def test_load_summary_aggregates_stats_per_http_method(tmp_path: Path) -> None:
    """Tests the loading and aggregation of load testing statistics from a CSV file.

    Args:
        tmp_path: A temporary path object used for creating and writing the mock
        statistics file.

    """
    stats = tmp_path / "locust_stats.csv"
    stats.write_text(
        "Type,Name,Request Count,Failure Count,Average Response Time,"
        "Min Response Time,Max Response Time\n"
        "GET,patients,4,1,20,10,30\n"
        "POST,patients,2,0,50,40,60\n"
        ",Aggregated,6,1,30,10,60\n",
        encoding="utf-8",
    )

    summary = _load_summary(stats)

    assert summary is not None
    assert summary.requests == 6
    assert summary.failures == 1
    assert summary.minimum_ms == 10
    assert summary.average_ms == 30
    assert summary.maximum_ms == 60
    assert summary.methods == {"GET": (4, 1), "POST": (2, 0)}
    assert summary.status_codes == {}
    assert not summary.has_invalid_values
    assert not summary.has_invalid_status_codes


def test_load_summary_marks_invalid_csv_metrics(tmp_path: Path) -> None:
    """Tests that the function correctly identifies invalid metrics when loading a CSV.

    File containing malformed data.

    Args:
        tmp_path: The temporary directory path used for creating and accessing the mock
        CSV file.

    """
    stats = tmp_path / "locust_stats.csv"
    stats.write_text(
        "Type,Name,Request Count,Failure Count,Average Response Time,"
        "Min Response Time,Max Response Time\n"
        "GET,patients,invalid,0,20,10,30\n",
        encoding="utf-8",
    )

    summary = _load_summary(stats)

    assert summary is not None
    assert summary.has_invalid_values


def test_load_summary_marks_non_finite_metrics_as_invalid(tmp_path: Path) -> None:
    """Tests that the summary loading function correctly identifies.

    And marks non-finite metrics (like NaN) as invalid.

    Args:
        tmp_path: A temporary path object used for creating a mock CSV file containing
        load test statistics.

    """
    stats = tmp_path / "locust_stats.csv"
    stats.write_text(
        "Type,Name,Request Count,Failure Count,Average Response Time,"
        "Min Response Time,Max Response Time\n"
        "GET,patients,1,0,nan,10,30\n",
        encoding="utf-8",
    )

    summary = _load_summary(stats)

    assert summary is not None
    assert summary.has_invalid_values


def test_loads_request_totals_per_http_status_code(tmp_path: Path) -> None:
    """Tests the loading of request totals grouped by HTTP status code from a CSV file.

    Args:
        tmp_path: A temporary path object used for creating and managing test files.

    """
    stats = tmp_path / "final_codes.csv"
    stats.write_text(
        "HTTP Code,Request Count,Average Response Time,"
        "Min Response Time,Max Response Time\n"
        "200,4,20,10,30\n404,2,50,40,60\n",
        encoding="utf-8",
    )

    assert _load_status_codes(stats) == (
        {
            "200": StatusCodeSummary(4, 20, 10, 30),
            "404": StatusCodeSummary(2, 50, 40, 60),
        },
        False,
    )


def test_status_code_metrics_report_invalid_rows(tmp_path: Path) -> None:
    """Tests that the status code metrics report correctly handles invalid rows in the.

    Input CSV file.

    Args:
        tmp_path: The temporary directory path used for creating and accessing test
        files.

    """
    stats = tmp_path / "final_codes.csv"
    stats.write_text(
        "HTTP Code,Request Count,Average Response Time,"
        "Min Response Time,Max Response Time\n"
        "200,1.5,20,10,30\n",
        encoding="utf-8",
    )

    assert _load_status_codes(stats) == ({}, True)


def test_runs_locust_and_prints_the_final_summary(tmp_path: Path) -> None:
    """Runs a load test using Locust.

    And asserts that the final summary is printed to the output.

    Args:
        tmp_path: A temporary path object used for creating configuration files.

    """
    class ApiHandler(BaseHTTPRequestHandler):
        """A handler class that inherits from BaseHTTPRequestHandler.

        And implements basic API endpoint logic for serving OpenAPI JSON and health
        checks.

        """

        def do_GET(self) -> None:  # noqa: N802 - required BaseHTTPRequestHandler method
            """Handles HTTP GET requests.

            Serving OpenAPI specification or health check status based on the request
            path.

            """
            if self.path == "/openapi.json":
                body = json.dumps(
                    {
                        "openapi": "3.0.3",
                        "servers": [{"url": server_url}],
                        "paths": {"/health": {"get": {}}},
                    }
                ).encode()
            elif self.path == "/health":
                body = b"{}"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """Logs a message to the console.

            Args:
                format: The format string for the log message.
                args: Positional arguments to be formatted into the log message.

            """
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
    server_url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / ".cilada.toml"
    config.write_text(
        "[api]\n"
        f'openapi_url = "{server_url}/openapi.json"\n'
        '\n[locust]\nusers = 1\nspawn_rate = 10\nrun_time = "1s"\n'
        '\n[test]\nenabled_methods = ["GET"]\ncases_per_operation = 1\n',
        encoding="utf-8",
    )

    try:
        result = CliRunner().invoke(app, ["run", "--config", str(config)])
    finally:
        server.shutdown()
        thread.join()

    assert result.exit_code == 0, result.output
    assert "Final load test summary" in result.output
    assert "Requests:" in result.output
    assert "GET:" in result.output
    assert "200:" in result.output
