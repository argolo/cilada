"""Locust runtime loaded by the temporary locustfile."""

from __future__ import annotations

import csv
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from locust import HttpUser, between, events, task

from cilada.config import should_mark_failure
from cilada.openapi import RequestCase, merge_request_headers


def _load_runtime() -> dict[str, Any]:
    """Loads the runtime configuration from a file specified by the.

    CILADA_RUNTIME_FILE environment variable.

    """
    path = os.environ.get("CILADA_RUNTIME_FILE")
    if not path:
        raise RuntimeError("CILADA_RUNTIME_FILE is not set.")
    with Path(path).open(encoding="utf-8") as stream:
        data: dict[str, Any] = json.load(stream)
    return data


RUNTIME = _load_runtime()
CASES = [RequestCase(**item) for item in RUNTIME["cases"]]


@dataclass(slots=True)
class StatusCodeMetric:
    """Aggregated metrics for an HTTP status code."""

    requests: int = 0
    total_response_time: float = 0.0
    minimum_response_time: float = float("inf")
    maximum_response_time: float = 0.0

    def add(self, response_time: float) -> None:
        """Records a new request's response time.

        And updates various metrics like total count, minimum, and maximum response
        times.

        Args:
            response_time: The measured duration of the request in seconds.

        """
        self.requests += 1
        self.total_response_time += response_time
        self.minimum_response_time = min(self.minimum_response_time, response_time)
        self.maximum_response_time = max(self.maximum_response_time, response_time)


HTTP_STATUS_CODES: dict[int | str, StatusCodeMetric] = {}


@events.request.add_listener  # type: ignore[untyped-decorator]
def collect_http_status_code(
    response: Any | None = None, response_time: float = 0.0, **_: Any
) -> None:
    """Accumulate metrics by status code, including requests without a response."""
    status_code = getattr(response, "status_code", None)
    metric_key = status_code if isinstance(status_code, int) else "no response"
    metric = HTTP_STATUS_CODES.setdefault(metric_key, StatusCodeMetric())
    metric.add(response_time)


@events.test_stop.add_listener  # type: ignore[untyped-decorator]
def write_final_stats(environment: Any, **_: Any) -> None:
    """Write final metrics, including runs shorter than the CSV interval."""
    destination = os.environ.get("CILADA_FINAL_STATS_FILE")
    if not destination:
        return
    fields = [
        "Type",
        "Name",
        "Request Count",
        "Failure Count",
        "Average Response Time",
        "Min Response Time",
        "Max Response Time",
    ]
    with Path(destination).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for entry in environment.stats.entries.values():
            writer.writerow(
                {
                    "Type": entry.method,
                    "Name": entry.name,
                    "Request Count": entry.num_requests,
                    "Failure Count": entry.num_failures,
                    "Average Response Time": entry.avg_response_time,
                    "Min Response Time": entry.min_response_time or 0,
                    "Max Response Time": entry.max_response_time or 0,
                }
            )

    codes_destination = os.environ.get("CILADA_FINAL_CODES_FILE")
    if not codes_destination:
        return
    with Path(codes_destination).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "HTTP Code",
                "Request Count",
                "Average Response Time",
                "Min Response Time",
                "Max Response Time",
            ],
        )
        writer.writeheader()
        for status_code, metric in sorted(
            HTTP_STATUS_CODES.items(), key=lambda item: str(item[0])
        ):
            writer.writerow(
                {
                    "HTTP Code": status_code,
                    "Request Count": metric.requests,
                    "Average Response Time": (
                        metric.total_response_time / metric.requests
                    ),
                    "Min Response Time": metric.minimum_response_time,
                    "Max Response Time": metric.maximum_response_time,
                }
            )


class OpenApiUser(HttpUser):
    """User that randomly selects contract-derived operations and cases."""

    host = str(RUNTIME["base_url"])
    wait_time = between(0.1, 1.0)

    @task
    def call_openapi_operation(self) -> None:
        """Calls a specific OpenAPI operation using the configured client."""
        case = random.choice(CASES)  # noqa: S311 - not a cryptographic use
        headers = merge_request_headers(
            RUNTIME["headers"],
            case.headers,
            set(RUNTIME["skipped_required_headers"]),
        )
        kwargs: dict[str, Any] = {
            "headers": headers,
            "params": case.params,
            "name": case.name,
            "timeout": RUNTIME["timeout_seconds"],
            "verify": RUNTIME["verify_tls"],
        }
        if case.json_body is not None:
            kwargs["json"] = case.json_body
        with self.client.request(
            case.method,
            case.path,
            catch_response=True,
            **kwargs,
        ) as response:
            if should_mark_failure(
                response.status_code, RUNTIME["failure_status_classes"]
            ):
                response.failure(f"HTTP {response.status_code}")
