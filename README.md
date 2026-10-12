# JSON Schema

Reliable structured output for Dify workflows: extract the JSON an LLM
produced, validate it against a JSON Schema, and get typed errors that
downstream branches can act on.

**Author:** [EFT](https://github.com/ztistic)
**Repo:** [dify-plugin-json-schema](https://github.com/ztistic/dify-plugin-json-schema)
**Version:** 1.0.0
**Type:** tool

## Why

An LLM node can be guided with a JSON Schema, but nothing guarantees the reply
actually matches it — or is even parseable JSON. When the model drifts,
downstream nodes either fail to parse the output or silently receive the wrong
shape. This plugin puts a deterministic quality gate after the LLM node, so a
broken answer becomes a typed, branchable result instead of a silent failure.

## Features

- **JSON Extractor** — pulls the first parseable JSON string out of a raw LLM
  answer. No guessing, no cleanup, no repair.
- **JSON Schema Validator** — validates a JSON string against a JSON Schema
  (drafts 2020-12 / 2019-09 / 07 / 06 / 04) and classifies every failure into
  a typed `error_type`.
- Runs offline: no network access, no model calls.

## Setup

Requires Dify ≥ 1.14.2. No credentials or configuration are needed.

Install **JSON Schema** from the Dify Marketplace, or upload the packaged
`json-schema-1.0.0.difypkg` via *Plugins → Install → Local Package*.

## Usage

```
LLM node -> JSON Extractor -> JSON Schema Validator -> branch on the results
```

### JSON Extractor

| Parameter    | Type   | Required | Description                            |
|--------------|--------|----------|----------------------------------------|
| `llm_output` | string | yes      | Raw answer text of the upstream LLM node |

Two unambiguous shapes are recognized, tried in order:

1. the entire input already is JSON, returned as-is;
2. a ```` ```json ```` or untagged fenced code block, returned verbatim.

JSON embedded bare in prose is outside these shapes and is reported as
`no_json_found`.

#### Outputs

The tool is designed not to raise: every classified failure returns a typed
payload, and an unexpected internal error is reported as `internal_error`
instead of propagating.

| Field        | Type    | Present    | Description                                  |
|--------------|---------|------------|----------------------------------------------|
| `found`      | boolean | always     | Whether a parseable JSON string was extracted |
| `json`       | string  | on success | The extracted JSON text, verbatim — feed it to the validator |
| `error_type` | string  | on failure | Failure category, see below                  |
| `error`      | string  | on failure | Human-readable explanation                   |

##### Error Types

| `error_type`    | Meaning                                          |
|-----------------|--------------------------------------------------|
| `invalid_input` | `llm_output` missing or blank                    |
| `no_json_found` | Not JSON as a whole; no parseable json fence     |
| `internal_error`| Unexpected failure, e.g. input nested too deeply |

### JSON Schema Validator

| Parameter      | Type   | Required | Description                                      |
|----------------|--------|----------|--------------------------------------------------|
| `json_input`   | string | yes      | JSON string to validate — typically the extractor's `json` |
| `schema_input` | string | yes      | JSON Schema; only inline `$ref` pointers resolve |

#### Outputs

The tool is designed not to raise: every classified failure returns a typed
payload, and an unexpected internal error is reported as `internal_error`
instead of propagating.

| Field         | Type    | Present    | Description                                   |
|---------------|---------|------------|-----------------------------------------------|
| `is_valid`    | boolean | always     | Whether the input satisfies the schema        |
| `message`     | string  | on success | `"Validation passed."`                        |
| `error_type`  | string  | on failure | Failure category, see below                   |
| `error`       | string  | on failure | Human-readable explanation, safe to feed back into a retry prompt |
| `path`        | array   | on failure | Location in the JSON that failed, e.g. `["tags", 2]` — always present, empty when not applicable |
| `schema_path` | array   | on failure | Location in the schema of the violated keyword, e.g. `["properties", "age", "minimum"]` — always present, empty when not applicable |

##### Error Types

| `error_type`        | Meaning                                                                |
|---------------------|------------------------------------------------------------------------|
| `invalid_input`     | A parameter is missing, blank, or not convertible to JSON text         |
| `invalid_json`      | `json_input` is not parseable JSON; `error` carries line and column    |
| `invalid_schema_json` | `schema_input` is not parseable JSON                                 |
| `schema_error`      | The schema itself violates its metaschema                              |
| `unsupported_draft` | `$schema` declares a draft other than 2020-12 / 2019-09 / 07 / 06 / 04 |
| `ref_resolution_error` | An inline `$ref` pointer cannot be resolved; remote refs are never fetched |
| `validation_failed` | Valid JSON, valid schema — the data does not match; `path` and `schema_path` point at the failure |
| `internal_error`    | Unexpected failure, e.g. nesting beyond interpreter depth              |

Notes:

- The validator does not clean its input: `json_input` is passed straight to
  `json.loads`, and anything not already valid JSON is reported as
  `invalid_json`.
- The schema is applied exactly as written; `additionalProperties: false` is
  how undeclared properties get rejected.
- `error`, `path` and `schema_path` are suitable for feeding back into a
  retry prompt.

## Limits

- The nesting boundary comes from the interpreter's recursion depth.
  Measured on CPython 3.12 with the default recursion limit: schemas up to
  ~95 levels and data up to ~100–200 levels are handled; deeper input
  returns a structured error.
- Only inline `$ref` pointers are resolved — never remote references, since
  the plugin does not touch the network.

## Implementation

Pure Python, built on the [jsonschema](https://pypi.org/project/jsonschema/)
library: its per-draft validator classes drive both metaschema checking and
instance validation, and inline `$ref` resolution goes through the bundled
`referencing` library. No network access anywhere.

## Privacy

The plugin runs offline and collects no data. See
[PRIVACY.md](./PRIVACY.md).

## Development

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
dify plugin package . -o json-schema-1.0.0.difypkg
```

For remote debugging, copy `.env.example` to `.env`, fill in
`REMOTE_INSTALL_URL` and `REMOTE_INSTALL_KEY` from your Dify instance, then
run `python -m main`.

## Icon

The plugin icon is the official JSON Schema logo
(<https://json-schema.org/logo-blue.svg>).

## License

[MIT](./LICENSE)
