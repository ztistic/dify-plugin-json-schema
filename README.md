# JSON Schema

Reliable structured output for Dify workflows: extract the JSON an LLM
produced, validate it against a JSON Schema, and get typed errors that
downstream branches can act on.

**Author:** [EFT](https://github.com/ztistic)
**Repo:** [dify-plugin-json-schema](https://github.com/ztistic/dify-plugin-json-schema)
**Version:** 1.0.0 **Type:** tool

## Why

An LLM node can be guided with a JSON Schema, but nothing guarantees the reply
actually matches it — or is even parseable JSON. When the model drifts,
downstream nodes either fail to parse the output or silently receive the wrong
shape. This plugin puts a deterministic quality gate after the LLM node, so a
broken answer becomes a typed, branchable result instead of a silent failure.

## Features

- **JSON Extract** — pulls the first parseable JSON string out of a text,
  typically a raw LLM answer. Whole-input JSON and trusted code fences are
  recognized by default; a JSON object or array embedded in surrounding prose
  is found only when `scan_embedded` is on. No guessing, no cleanup, no repair.
- **JSON Validate** — validates a JSON string against a JSON Schema (drafts
  2020-12 / 2019-09 / 07 / 06 / 04) and classifies every failure into a typed
  `error_type`.
- Runs offline: no network access, no model calls.

## Setup

Requires Dify ≥ 1.14.2. No credentials or configuration are needed.

Available as **JSON Schema** on the Dify Marketplace; the packaged
`json-schema-1.0.0.difypkg` can also be uploaded via *Plugins → Install →
Local Package*.

## Usage

```
LLM node -> JSON Extract -> JSON Validate -> branch on the results
```

Both tools share the same output contract:

- The tool never raises: every classified failure returns a typed payload, and
  an unexpected internal error is reported as `internal_error`.
- Each invocation emits a text message (human-readable summary) first, then
  the JSON payload, then one variable message per declared output field — so
  downstream nodes can reference the fields below as typed variables.
- A parameter value that arrives as a non-string (e.g. an already-parsed
  object from an upstream node) is converted to JSON text before processing.

### JSON Extract

| Parameter       | Type    | Required | Description                                          |
|-----------------|---------|----------|------------------------------------------------------|
| `text`          | string  | yes      | Text containing JSON, typically the output of an LLM |
| `scan_embedded` | boolean | no       | Off by default; enables shape 3 below                |

`scan_embedded` is read strictly: only the boolean value `true` enables the
embedded scan; other truthy values do not.

#### Recognized shapes

Three shapes are tried in order, and the first hit is returned:

1. **Whole input** — the entire input already is JSON.
2. **Code fence** — a ```` ```json ```` or untagged fenced code block. The
   language tag match is case-insensitive and a closing fence is required;
   the first fence whose content parses wins.
3. **Embedded scan** — the first JSON object or array embedded anywhere in
   the text, active only when `scan_embedded` is on. The scan is seeded at
   `{` and `[`, so bare numbers, strings and literals in prose are never
   candidates, and JSON inside an other-language or unclosed fence becomes
   reachable.

Every candidate is decoded before it is accepted, and the returned string is
a verbatim slice of the input (surrounding whitespace trimmed) — never
re-serialized. Decoding is strict: the non-standard constants `NaN` and
`Infinity` are not valid JSON and are rejected. Text holding none of the
checked shapes is reported as `no_json_found`; the detail states whether the
embedded scan was off.

#### Outputs

| Field          | Type    | Present    | Description                                        |
|----------------|---------|------------|----------------------------------------------------|
| `found`        | boolean | always     | Whether a parseable JSON string was extracted      |
| `json_text`    | string  | on success | The extracted JSON text — feed it to the validator |
| `error_type`   | string  | on failure | Failure category, see below                        |
| `error_detail` | string  | on failure | Human-readable explanation                         |

The text message carries the extracted JSON string on success and is empty
on failure.

| `error_type`     | Meaning                                                     |
|------------------|-------------------------------------------------------------|
| `invalid_input`  | `text` missing, blank, or not convertible to JSON text      |
| `no_json_found`  | No parseable JSON in the shapes that were checked           |
| `internal_error` | Unexpected failure, e.g. input nested too deeply            |

### JSON Validate

| Parameter      | Type   | Required | Description                                                     |
|----------------|--------|----------|-----------------------------------------------------------------|
| `json_input`   | string | yes      | JSON string to validate — typically the extractor's `json_text` |
| `schema_input` | string | yes      | JSON Schema; only inline `$ref` pointers resolve                |

#### Draft selection

The validator class is picked from the schema's `$schema` declaration:

- absent, blank, or the generic `http(s)://json-schema.org/schema#` URI →
  Draft 2020-12;
- an official draft URI (`.../draft/2020-12/schema`, `.../draft-07/schema#`,
  ...) or a bare shorthand (`draft-07`, `draft/2020-12`) → the matching
  draft;
- anything else — including a third-party URI that merely mentions a draft
  number — is rejected as `unsupported_draft`.

A boolean schema (`true` / `false`) is also accepted.

#### Outputs

| Field                  | Type    | Present    | Description                                                                                       |
|------------------------|---------|------------|---------------------------------------------------------------------------------------------------|
| `is_valid`             | boolean | always     | Whether the input satisfies the schema                                                            |
| `error_type`           | string  | on failure | Failure category, see below                                                                       |
| `error_detail`         | string  | on failure | Human-readable explanation, safe to feed back into a retry prompt                                 |
| `json_path`            | string  | on failure | Location in the JSON that failed as a JSONPath string, e.g. `$.tags[1]`; empty when not applicable |
| `absolute_path`        | array   | on failure | The same location as raw path segments, e.g. `["tags", 1]`; empty when not applicable             |
| `absolute_schema_path` | array   | on failure | Location in the schema of the violated keyword as raw path segments, e.g. `["properties", "age", "minimum"]`; empty when not applicable |

On success the payload is exactly `{"is_valid": true}`; on failure all six
fields are present, so branches need no defensive checks. The text message is
`Validation passed.` on success and a `Validation failed [error_type]` summary
carrying the JSON path and the schema path on failure.

| `error_type`           | Meaning                                                                                        |
|------------------------|------------------------------------------------------------------------------------------------|
| `invalid_input`        | A parameter is missing, blank, or not convertible to JSON text                                 |
| `invalid_json`         | `json_input` is not parseable JSON; `error_detail` carries line and column                     |
| `invalid_schema_json`  | `schema_input` is not parseable JSON                                                           |
| `schema_error`         | The schema is neither an object nor a boolean, or violates its metaschema                      |
| `unsupported_draft`    | `$schema` declares a draft other than 2020-12 / 2019-09 / 07 / 06 / 04                         |
| `ref_resolution_error` | An inline `$ref` pointer cannot be resolved; remote refs are never fetched                     |
| `validation_failed`    | Valid JSON, valid schema — the data does not match; the three path fields point at the failure |
| `internal_error`       | Unexpected failure, e.g. nesting beyond interpreter depth or a circular `$ref`                 |

Notes:

- The validator does not clean its input: `json_input` goes straight to
  `json.loads`, and anything not already valid JSON is reported as
  `invalid_json`.
- Decoding is strict: the non-standard constants `NaN` and `Infinity` are
  rejected as `invalid_json` / `invalid_schema_json`.
- The schema is applied exactly as written; undeclared properties are rejected
  only where the schema declares `additionalProperties: false`.
- `error_detail`, `json_path` and `absolute_schema_path` are suitable for
  feeding back into a retry prompt.

## Limits

- The nesting boundary comes from the interpreter's recursion depth. Measured
  on CPython 3.12 with the default recursion limit: schemas up to ~95 levels
  and data up to ~100–200 levels are handled; deeper input returns a
  structured error.
- Only inline `$ref` pointers are resolved — never remote references, since
  the plugin does not touch the network.

## Implementation

Pure Python. Validation is built on the
[jsonschema](https://pypi.org/project/jsonschema/) library: its per-draft
validator classes drive both metaschema checking and instance validation, and
inline `$ref` resolution goes through the bundled `referencing` library.
Extraction uses only the standard library (`json`, `re`). No network access
anywhere.

## Privacy

The plugin runs offline and collects no data. See
[PRIVACY.md](./PRIVACY.md).

## Development

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
dify plugin package . -o json-schema-1.0.0.difypkg
```

For remote debugging, copy `.env.example` to `.env`, fill in
`REMOTE_INSTALL_URL` and `REMOTE_INSTALL_KEY` from the Dify instance, then run
`python -m main`.

## Icon

The plugin icon is the official JSON Schema logo
(<https://json-schema.org/logo-blue.svg>).

## License

[MIT](./LICENSE)
