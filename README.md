# Dify JSON Schema Plugin

**Author:** [EFT](https://github.com/ztistic)
**Repo:** [dify-plugin-json-schema](https://github.com/ztistic/dify-plugin-json-schema)
**Version:** 1.0.0
**Type:** tool

## Description

Dify's LLM node can be guided with a JSON Schema, but it cannot guarantee the
result actually matches. When the model drifts, downstream nodes fail on parse
or silently receive the wrong shape, without a clear reason.

This plugin adds a **deterministic quality gate** right after the LLM node. It
parses the model output, validates it against your schema with
[jsonschema](https://pypi.org/project/jsonschema/), and returns a typed result
that downstream conditional branches can act on. It separates three different
kinds of problems, which is what makes automated recovery possible:

- the model did not emit valid JSON at all,
- your JSON Schema itself is broken,
- the JSON is valid but does not satisfy the schema.

Validation runs entirely inside the plugin runtime: no credentials, no
endpoint, no network access.

## Requirements

- Dify 1.14.2 or later

## Installation

1. From Dify Marketplace: search "JSON Schema" in the Plugins page and install.
2. Or install from a local `.difypkg`: Plugins -> Install Plugin -> Via Local File.

## Tools

### JSON Schema Validator

| Parameter      | Type     | Required | Default | Form   | Description                                        |
|----------------|----------|----------|---------|--------|----------------------------------------------------|
| `json_input`   | `string` | Yes      | -       | `llm`  | The JSON string to validate                        |
| `schema_input` | `string` | Yes      | -       | `llm`  | The JSON Schema to validate against                |
| `strict_mode`  | `select` | No       | `false` | `form` | Reject properties that the schema does not define  |

If a parameter arrives already decoded as an object or an array, it is
serialized back to JSON first. A single Markdown code fence around the JSON is
tolerated, including a sentence in front of it, because that is how LLMs
usually emit structured output; plain (invalid) fenced garbage is still
reported as `invalid_json`.

### Nesting depth

`jsonschema` validates a schema against its metaschema in pure Python and
consumes roughly ten interpreter frames per nesting level, which would reject
any schema nested deeper than ~100 levels under CPython's default recursion
limit. The plugin therefore raises the recursion limit for the validation phase
(and restores it afterwards), which supports schemas up to roughly 1900 levels.

Beyond that, or for JSON documents too deep for the standard parser, the tool
still answers with a structured error instead of crashing:

| Situation                                        | `error_type`          |
|--------------------------------------------------|-----------------------|
| JSON data too deep for `json.loads`              | `invalid_json`        |
| JSON Schema too deep for `json.loads`            | `invalid_schema_json` |
| Schema too deep for metaschema checking          | `schema_error`        |
| Data or schema too deep for validation           | `internal_error`      |

### Outputs

Every invocation emits two messages:

- **text** - a human-readable summary, starting with either `Validation
  passed.` or `Validation failed [error_type]: ...`, followed by the JSON path
  and the schema path.
- **json** - a structured payload for downstream nodes.

Success payload:

```json
{
  "is_valid": true,
  "message": "Validation passed."
}
```

Failure payload (all four fields are always present):

```json
{
  "is_valid": false,
  "error_type": "validation_failed",
  "error": "'age' is a required property",
  "path": [],
  "schema_path": ["required"]
}
```

- `path` - list pointing at the offending location inside the JSON data
  (the root is `[]`).
- `schema_path` - list pointing at the schema rule that was violated.

### Error Types

| `error_type`            | Meaning                                             | Suggested reaction                     |
|-------------------------|-----------------------------------------------------|----------------------------------------|
| `invalid_input`         | `json_input` or `schema_input` is empty             | Fix the node wiring                    |
| `invalid_json`          | The data is not valid JSON                          | Ask the model to re-emit, or retry     |
| `invalid_schema_json`   | The schema is not valid JSON                        | Fix the schema text                    |
| `schema_error`          | Valid JSON, but not a valid JSON Schema             | Fix the schema structure               |
| `unsupported_draft`     | `$schema` points at an unsupported draft            | Switch to a supported draft            |
| `ref_resolution_error`  | A `$ref` cannot be resolved                         | Inline the referenced definition       |
| `validation_failed`     | Data is valid JSON but does not match the schema    | Patch the fields at `path`, then retry |
| `internal_error`        | Unexpected failure, never thrown as an exception    | Report it as a bug                     |

No input can make the tool throw: every failure path returns a structured
payload.

## Supported Drafts

| Draft     | `$schema` URI                                      |
|-----------|----------------------------------------------------|
| 2020-12   | `https://json-schema.org/draft/2020-12/schema`     |
| 2019-09   | `https://json-schema.org/draft/2019-09/schema`     |
| 7         | `http://json-schema.org/draft-07/schema#`          |
| 6         | `http://json-schema.org/draft-06/schema#`          |
| 4         | `http://json-schema.org/draft-04/schema#`          |

When `$schema` is omitted, or when it is the legacy generic pointer
`http://json-schema.org/schema#`, Draft 2020-12 is used. Draft 3 and unknown
URIs return `unsupported_draft`.

Only **inline** `$ref` pointers (for example `#/$defs/Address`) can be
resolved; remote references return `ref_resolution_error` instead of being
fetched over the network.

## Strict Mode

With `strict_mode` enabled, the plugin walks the schema and adds
`additionalProperties: false` to every object subschema that does not already
control extra keys, so unexpected fields are rejected. The walk covers
`properties`, `patternProperties`, `$defs`, `definitions`,
`dependentSchemas`, `items`, `prefixItems`, `allOf`, `anyOf`, `oneOf`, `not`,
`if`/`then`/`else`, `contains`, `propertyNames` and Draft-07 `dependencies`. A
subschema is treated as an object when its `type` is `"object"` or includes it
(for example `["object", "null"]`), or when it declares `properties` or
`required` without an explicit `type`. The original schema is never mutated.

## Workflow Pattern

Place the validator between the LLM node and the consumer, then branch on
`is_valid`:

```
LLM node -> JSON Schema Validator -> is_valid true  -> normal flow
                                  -> is_valid false -> error_type branch
                                                       validation_failed   -> retry with the error message
                                                       invalid_json        -> retry with stricter instructions
                                                       schema_error        -> alert the workflow author
```

Feeding `error`, `path` and `schema_path` back into the retry prompt lets the
model fix precisely the field that broke.

## Privacy

All validation happens in-memory inside the plugin runtime. Nothing is
collected, stored, logged or transmitted, and no outbound connection is made.
See [PRIVACY.md](./PRIVACY.md) for details.

## Performance

Measured with the bundled test payload (an array of records with nested
objects), on Python 3.12, single invocation:

| Payload size | Total time |
|--------------|------------|
| 8 KB         | ~3 ms      |
| 32 KB        | ~7 ms      |
| 128 KB       | ~22 ms     |
| 512 KB       | ~82 ms     |
| 1 MB         | ~160 ms    |

Roughly 95% of that time is spent inside `jsonschema` itself traversing the
document, which is inherent to a pure-Python validator and was the accepted
trade-off of the library choice. Strict mode adds roughly 10% because the
schema is deep-copied before validation.

## Development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Package with the [Dify Plugin CLI](https://github.com/langgenius/dify-plugin-daemon/releases):

```bash
dify plugin package . -o json-schema-1.0.0.difypkg
```

For remote debugging, copy `.env.example` to `.env`, fill in
`REMOTE_INSTALL_URL` and `REMOTE_INSTALL_KEY` from your Dify instance, then run
`python -m main`.

## Project Layout

```
dify-plugin-json-schema/
├── main.py                          # Plugin entrypoint
├── manifest.yaml                    # Plugin metadata
├── requirements.txt                 # Runtime dependencies
├── provider/
│   ├── json-schema.yaml             # Provider configuration
│   └── json-schema.py               # Provider credentials (none needed)
├── tools/
│   ├── json_schema_validator.yaml   # Tool definition
│   └── json_schema_validator.py     # Tool implementation
├── utils/
│   └── schema_utils.py              # Pure validation helpers
├── tests/                           # Unit tests
└── _assets/icon.svg                 # Plugin icon
```

## License

[MIT](./LICENSE)
