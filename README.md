# Cilada

> É uma cilada, Bino! 🚚

Cilada is a Python 3.11+ CLI that reads an online OpenAPI contract, generates
request cases, and runs load tests with Locust.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

Create a commented configuration template:

```bash
cilada config init
```

The command never overwrites an existing file unless `--force` is supplied. Use
`--path path/.cilada.toml` to create the file elsewhere. Keep secrets out of
version control and reference environment variables such as
`Authorization = "Bearer ${CILADA_TOKEN}"`.

## Usage

```bash
cilada run
cilada run --openapi-url https://sandbox.example.com/openapi.json
cilada run --dry-run
cilada run --non-interactive
```

Interactive runs request a missing OpenAPI URL and required headers. The OpenAPI
URL is required to load the contract. Sensitive header names (`Authorization`,
`token`, and `key`) use hidden input. Declining a required header triggers an
explicit confirmation; accepted runs omit that header from requests.

## Progress and results

The CLI displays three setup steps. During execution, Locust shows its native
statistics table. Its `Name` column uses the shortest unique URL suffix and its
`Type` column shows the HTTP method.

The final summary reports request and failure counts, global minimum/average/
maximum response times, totals by HTTP method, and metrics by HTTP status code.
Each status code includes request count and minimum, average, and maximum response
times. Requests that fail before receiving an HTTP response are listed as
`no response`.

## Case generation

- `test.enabled_methods` controls executed methods.
- `include_paths` and `exclude_paths` accept glob patterns such as `/patients/*`.
- `cases_per_operation` produces variants from examples, defaults, enums, optional
  fields, and boundary values.
- `test.failure_status_classes` defaults to `[5]`; use `[4, 5]` to also mark 4xx
  responses as failures.

## Safety

The default methods are `GET`, `HEAD`, and `OPTIONS`. Enable `POST`, `PUT`,
`PATCH`, or `DELETE` only in an isolated, authorized environment with disposable
data.

## Quality

```bash
make unit-test
make lint
make typecheck
```

Run `make install` to install development dependencies, `make build` to create
distribution artifacts, and `make format` (or `make formatter`) to format the
project.

## Deliberate limitations

- JSON Schema `$ref` is not expanded.
- Only `application/json` request bodies are generated.
- OAuth2 token refresh requires a future hook; static headers work for valid tokens.

Portuguese documentation is available in [README_PT.md](README_PT.md).
