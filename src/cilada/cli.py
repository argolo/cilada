"""Cilada command-line interface."""

from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import typer

from cilada.config import ConfigurationError, Settings, load_settings
from cilada.openapi import (
    OpenApiError,
    build_cases,
    fetch_spec,
    required_global_headers,
    resolve_base_url,
)

BANNER = "É uma cilada, Bino! 🚚"
app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
config_app = typer.Typer(no_args_is_help=True, help="Manage configuration.")
app.add_typer(config_app, name="config")

CONFIG_TEMPLATE = """\
# Cilada configuration. Do not commit secrets to this file.
[api]
# openapi_url = "https://api.example.com/openapi.json"
# base_url = "https://api.example.com"
verify_tls = true
timeout_seconds = 30

[api.headers]
# Authorization = "Bearer ${CILADA_TOKEN}"

[test]
enabled_methods = ["GET", "HEAD", "OPTIONS"]
include_paths = []
exclude_paths = []
cases_per_operation = 3
# HTTP classes that count as failures: 5 = 5xx; use [4, 5] for 4xx and 5xx.
failure_status_classes = [5]

[locust]
users = 10
spawn_rate = 2.0
run_time = "1m"
headless = true
web_host = "127.0.0.1"
web_port = 8089
# csv_prefix = "reports/cilada"
# html_report = "reports/cilada.html"
"""


@app.callback()
def callback() -> None:
    """OpenAPI contract-driven load testing."""


@config_app.command("init")
def config_init(
    path: Annotated[
        Path,
        typer.Option("--path", help="Destination TOML file."),
    ] = Path(".cilada.toml"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing configuration file."),
    ] = False,
) -> None:
    """Create a commented .cilada.toml ready for editing."""
    if path.exists() and not force:
        _abort(f"{path} already exists; use --force to overwrite it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    typer.secho(f"Configuration created at {path}", fg=typer.colors.GREEN, bold=True)


def _abort(message: str) -> None:
    """Aborts the program by printing an error message.

    And exiting with a non-zero status code.

    Args:
        message: The error message to display when aborting.

    """
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(2)


def _stage(number: int, message: str) -> None:
    """Display a highlighted setup step."""
    typer.echo()
    typer.secho(f"[{number}/3] {message}", fg=typer.colors.CYAN, bold=True)


@dataclass(frozen=True, slots=True)
class LoadSummary:
    """Consolidated metrics parsed from Locust statistics CSV files."""

    requests: int
    failures: int
    minimum_ms: float
    average_ms: float
    maximum_ms: float
    methods: dict[str, tuple[int, int]]
    status_codes: dict[str, StatusCodeSummary]
    has_invalid_values: bool
    has_invalid_status_codes: bool


@dataclass(frozen=True, slots=True)
class StatusCodeSummary:
    """Consolidated metrics for an HTTP status code."""

    requests: int
    average_ms: float
    minimum_ms: float
    maximum_ms: float


def _number(value: str | None) -> float:
    """Converts a string representation of a number into a floating-point number.

    Defaulting to 0.0 if the conversion fails or results in an infinite value.

    Args:
        value: The input string to be converted to a float.

    """
    try:
        number = float(value or 0)
    except ValueError:
        return 0.0
    return number if math.isfinite(number) else 0.0


def _is_number(value: str | None) -> bool:
    """Checks if the given string value represents a finite number.

    Args:
        value: The string value to check.

    """
    try:
        return math.isfinite(float(value or 0))
    except ValueError:
        return False


def _is_count(value: str | None) -> bool:
    """Checks if a given value is a non-negative integer.

    Args:
        value: The string value to check.

    """
    return _is_number(value) and _number(value).is_integer() and _number(value) >= 0


def _count(value: str | None) -> int:
    """Counts the number of occurrences or values in a given string.

    Args:
        value: The input value to be counted.

    """
    return int(_number(value)) if _is_count(value) else 0


def _load_summary(stats_file: Path) -> LoadSummary | None:
    """Read per-endpoint rows while excluding Locust's aggregate row."""
    if not stats_file.exists():
        return None
    with stats_file.open(encoding="utf-8", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row.get("Type")]
    if not rows:
        return None

    numeric_fields = (
        "Request Count",
        "Failure Count",
        "Average Response Time",
        "Min Response Time",
        "Max Response Time",
    )
    has_invalid_values = any(
        not _is_count(row.get(field))
        if field in {"Request Count", "Failure Count"}
        else not _is_number(row.get(field))
        for row in rows
        for field in numeric_fields
    )

    requests = sum(_count(row.get("Request Count")) for row in rows)
    failures = sum(_count(row.get("Failure Count")) for row in rows)
    active_rows = [row for row in rows if _count(row.get("Request Count")) > 0]
    average = (
        sum(
            _number(row.get("Average Response Time")) * _count(row.get("Request Count"))
            for row in active_rows
        )
        / requests
        if requests
        else 0.0
    )
    methods: dict[str, tuple[int, int]] = {}
    for row in rows:
        method = row["Type"]
        count, failed = methods.get(method, (0, 0))
        methods[method] = (
            count + _count(row.get("Request Count")),
            failed + _count(row.get("Failure Count")),
        )
    return LoadSummary(
        requests=requests,
        failures=failures,
        minimum_ms=min(
            (_number(row.get("Min Response Time")) for row in active_rows), default=0
        ),
        average_ms=average,
        maximum_ms=max(
            (_number(row.get("Max Response Time")) for row in active_rows), default=0
        ),
        methods=methods,
        status_codes={},
        has_invalid_values=has_invalid_values,
        has_invalid_status_codes=False,
    )


def _load_status_codes(stats_file: Path) -> tuple[dict[str, StatusCodeSummary], bool]:
    """Loads and parses status code summary statistics from a specified CSV file.

    Args:
        stats_file: The path to the CSV file containing the status code statistics.

    """
    if not stats_file.exists():
        return {}, False
    with stats_file.open(encoding="utf-8", newline="") as stream:
        rows = csv.DictReader(stream)
        fields = (
            "Request Count",
            "Average Response Time",
            "Min Response Time",
            "Max Response Time",
        )
        parsed_rows = list(rows)
        invalid = any(
            not _is_count(row.get("Request Count"))
            or any(not _is_number(row.get(field)) for field in fields[1:])
            for row in parsed_rows
            if row.get("HTTP Code")
        )
        return {
            row["HTTP Code"]: StatusCodeSummary(
                requests=_count(row.get("Request Count")),
                average_ms=_number(row.get("Average Response Time")),
                minimum_ms=_number(row.get("Min Response Time")),
                maximum_ms=_number(row.get("Max Response Time")),
            )
            for row in parsed_rows
            if row.get("HTTP Code")
            and _is_count(row.get("Request Count"))
            and all(_is_number(row.get(field)) for field in fields[1:])
        }, invalid


def _print_load_summary(
    stats_file: Path, final_stats_file: Path, status_codes_file: Path
) -> None:
    """Print the final summary, including after a failed execution."""
    summary = _load_summary(final_stats_file) or _load_summary(stats_file)
    typer.echo()
    typer.secho("Final load test summary", fg=typer.colors.GREEN, bold=True)
    if summary is None:
        typer.secho(
            "  Locust statistics could not be collected.",
            fg=typer.colors.YELLOW,
        )
        return
    status_codes, has_invalid_status_codes = _load_status_codes(status_codes_file)
    summary = LoadSummary(
        requests=summary.requests,
        failures=summary.failures,
        minimum_ms=summary.minimum_ms,
        average_ms=summary.average_ms,
        maximum_ms=summary.maximum_ms,
        methods=summary.methods,
        status_codes=status_codes,
        has_invalid_values=summary.has_invalid_values,
        has_invalid_status_codes=has_invalid_status_codes,
    )
    typer.echo(f"  Requests: {summary.requests}")
    typer.echo(f"  Failures: {summary.failures}")
    typer.echo(
        "  Response time: "
        f"minimum {summary.minimum_ms:.1f} ms | "
        f"average {summary.average_ms:.1f} ms | "
        f"maximum {summary.maximum_ms:.1f} ms"
    )
    typer.secho("  Totals by HTTP method", fg=typer.colors.CYAN, bold=True)
    for method, (requests, failures) in sorted(summary.methods.items()):
        typer.echo(f"    {method}: {requests} requests | {failures} failures")
    typer.secho("  Totals by HTTP status code", fg=typer.colors.CYAN, bold=True)
    for status_code, metric in sorted(summary.status_codes.items()):
        typer.echo(
            f"    {status_code}: {metric.requests} requests | "
            f"min. {metric.minimum_ms:.1f} ms | "
            f"avg. {metric.average_ms:.1f} ms | "
            f"max. {metric.maximum_ms:.1f} ms"
        )
    if summary.has_invalid_values:
        typer.secho(
            "  Warning: the CSV contains invalid metrics; non-numeric values were "
            "treated as zero.",
            fg=typer.colors.YELLOW,
        )
    if summary.has_invalid_status_codes:
        typer.secho(
            "  Warning: the HTTP status metrics file contains invalid rows.",
            fg=typer.colors.YELLOW,
        )


def _complete_interactively(settings: Settings, interactive: bool) -> None:
    """Completes the OpenAPI specification interactively if it is not already.

    Configured.

    Args:
        settings: The settings object containing configuration details, including API
        information.
        interactive: A boolean flag indicating whether interactive prompting should be
        used.

    """
    if not settings.api.openapi_url:
        if not interactive:
            _abort("provide --openapi-url or api.openapi_url in .cilada.toml")
        settings.api.openapi_url = typer.prompt("/openapi.json URL")


def _ask_missing_headers(
    settings: Settings, required: set[str], interactive: bool
) -> set[str]:
    """Checks if necessary API headers are present in the settings.

    And prompts the user to provide them interactively if they are missing.

    Args:
        settings: The application settings object containing existing API configuration.
        required: A set of required header names (strings) that must be provided for the
        API call to succeed.
        interactive: If True, prompts the user interactively when a missing required
        header is detected.

    """
    existing = {name.lower() for name in settings.api.headers}
    missing: list[str] = []
    for header in sorted(required, key=str.lower):
        if header.lower() in existing:
            continue
        if interactive and typer.confirm(
            f"Do you want to provide the required {header} header?", default=True
        ):
            secret = any(
                token in header.lower() for token in ("authorization", "token", "key")
            )
            settings.api.headers[header] = typer.prompt(
                f"Value for required {header} header", hide_input=secret
            )
        else:
            missing.append(header)

    if missing and not typer.confirm(
        f"Required headers are missing ({', '.join(missing)}). Run the tests anyway?",
        default=False,
    ):
        _abort("execution cancelled because required headers are missing")
    return {header.lower() for header in missing}


def _locust_command(
    settings: Settings, locustfile: Path, csv_prefix: Path
) -> list[str]:
    """Generates a list of command-line arguments for running Locust.

    Args:
        settings: The settings object containing configuration parameters for Locust,
        such as users and run time.
        locustfile: The path to the locust file that contains the test scenario.
        csv_prefix: The prefix path used for generating CSV reports.

    """
    config = settings.locust
    command = [sys.executable, "-m", "locust", "-f", str(locustfile)]
    if config.headless:
        command.extend(
            [
                "--headless",
                "--users",
                str(config.users),
                "--spawn-rate",
                str(config.spawn_rate),
                "--run-time",
                config.run_time,
            ]
        )
    else:
        command.extend(
            ["--web-host", config.web_host, "--web-port", str(config.web_port)]
        )
    csv_prefix.parent.mkdir(parents=True, exist_ok=True)
    command.extend(["--csv", str(csv_prefix)])
    if config.html_report:
        Path(config.html_report).parent.mkdir(parents=True, exist_ok=True)
        command.extend(["--html", config.html_report])
    return command


@app.command()
def run(
    openapi_url: Annotated[
        str | None,
        typer.Option("--openapi-url", "-u", help="OpenAPI document URL."),
    ] = None,
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Configuration TOML file."),
    ] = Path(".cilada.toml"),
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help=(
                "Do not request values; confirm before running without "
                "required headers."
            ),
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Validate and list cases without generating load."
        ),
    ] = False,
) -> None:
    """Load OpenAPI and run scenarios through Locust."""
    try:
        settings = load_settings(config)
        if openapi_url:
            settings.api.openapi_url = openapi_url
        _complete_interactively(settings, not non_interactive)
        _stage(1, "Loading the OpenAPI contract...")
        spec = fetch_spec(settings.api)
        skipped_required_headers = _ask_missing_headers(
            settings,
            required_global_headers(spec, settings.test),
            not non_interactive,
        )
        base_url = resolve_base_url(spec, settings.api)
        _stage(2, "Generating load scenarios...")
        cases = build_cases(spec, settings.test)
    except (ConfigurationError, OpenApiError) as exc:
        _abort(str(exc))

    if not cases:
        _abort("no operation matches the configured methods and filters")
    typer.echo()
    typer.secho("Load test overview", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  Contract: {settings.api.openapi_url}")
    typer.echo(f"  Target: {base_url}")
    typer.echo(f"  Generated cases: {len(cases)}")
    if dry_run:
        for case in cases:
            typer.echo(f"- {case.name}")
        return

    _stage(3, "Load test running")
    typer.secho(
        "The Locust table will display average response times and failures.",
        fg=typer.colors.BRIGHT_BLACK,
    )
    runtime = {
        "base_url": base_url,
        "headers": settings.api.headers,
        "verify_tls": settings.api.verify_tls,
        "timeout_seconds": settings.api.timeout_seconds,
        "failure_status_classes": settings.test.failure_status_classes,
        "skipped_required_headers": sorted(skipped_required_headers),
        "cases": [asdict(case) for case in cases],
    }
    with tempfile.TemporaryDirectory(prefix="cilada-") as directory:
        temp_dir = Path(directory)
        csv_prefix = (
            Path(settings.locust.csv_prefix)
            if settings.locust.csv_prefix
            else temp_dir / "locust"
        )
        runtime_file = temp_dir / "runtime.json"
        final_stats_file = temp_dir / "final_stats.csv"
        final_codes_file = temp_dir / "final_codes.csv"
        runtime_file.write_text(json.dumps(runtime), encoding="utf-8")
        runtime_file.chmod(0o600)
        locustfile = temp_dir / "locustfile.py"
        locustfile.write_text(
            "from cilada.runtime import OpenApiUser\n", encoding="utf-8"
        )
        environment = {
            **os.environ,
            "CILADA_RUNTIME_FILE": str(runtime_file),
            "CILADA_FINAL_STATS_FILE": str(final_stats_file),
            "CILADA_FINAL_CODES_FILE": str(final_codes_file),
        }
        try:
            result = subprocess.run(  # noqa: S603 - arguments are a controlled list
                _locust_command(settings, locustfile, csv_prefix),
                env=environment,
                check=False,
            )
        finally:
            _print_load_summary(
                csv_prefix.with_name(f"{csv_prefix.name}_stats.csv"),
                final_stats_file,
                final_codes_file,
            )
        raise typer.Exit(result.returncode)


def main() -> None:
    """Display the slogan before delegating parsing to Typer."""
    typer.echo()
    typer.secho(BANNER, fg=typer.colors.YELLOW, bold=True)
    typer.echo()
    app()


if __name__ == "__main__":
    main()
