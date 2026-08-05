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

The `.cilada.toml` configuration file is **optional**. All settings can be passed directly via CLI arguments or defined in `.cilada.toml`.

```bash
# Run using .cilada.toml (if present)
cilada run

# Run without configuration file by providing --openapi-url via CLI:
cilada run --openapi-url https://sandbox.example.com/openapi.json

# Provide full configuration via CLI arguments:
cilada run \
  --openapi-url https://api.example.com/openapi.json \
  --users 20 \
  --spawn-rate 5.0 \
  --run-time 2m \
  -H "Authorization: Bearer mytoken" \
  -H "X-Tenant: mytenant" \
  -m GET -m POST \
  --cases-per-operation 3 \
  --timeout-seconds 15

# Validate contract and list cases without load:
cilada run --dry-run --openapi-url https://sandbox.example.com/openapi.json

# Non-interactive run (bypasses all interactive prompts and confirmations):
cilada run --non-interactive --openapi-url https://sandbox.example.com/openapi.json
```

### Configuration Precedence

Order of precedence: **CLI Arguments > `.cilada.toml` file > Standard Defaults**.

All CLI arguments available for `cilada run`:
- **API**: `--openapi-url` (`-u`), `--base-url` (`-b`), `--header` (`-H`), `--verify-tls`/`--no-verify-tls`, `--timeout-seconds`
- **Test**: `--enabled-methods` (`-m`), `--include-paths`, `--exclude-paths`, `--cases-per-operation`, `--failure-status-classes`
- **Locust**: `--users`, `--spawn-rate`, `--run-time`, `--headless`/`--no-headless`, `--web-host`, `--web-port`, `--csv-prefix`, `--html-report`

Interactive runs request a missing OpenAPI URL and required headers if not supplied via CLI or TOML file. Sensitive header names (`Authorization`, `token`, and `key`) use hidden input. Declining a required header triggers an explicit confirmation; accepted runs omit that header from requests. With `--non-interactive`, zero interaction is performed (all prompts and confirmations are bypassed).

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

- `test.enabled_methods` / `-m` controls executed methods.
- `include_paths` and `exclude_paths` accept glob patterns such as `/patients/*`.
- `cases_per_operation` / `--cases-per-operation` produces variants from examples, defaults, enums, optional fields, and boundary values.
- `test.failure_status_classes` / `--failure-status-classes` defaults to `[5]`; use `[4, 5]` to also mark 4xx responses as failures.

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
