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

| Parameter      | Type     | Required | Form   | Description                                 |
|----------------|----------|----------|--------|---------------------------------------------|
| `json_input`   | `string` | Yes      | `llm`  | The JSON string to validate                 |
| `schema_input` | `string` | Yes      | `llm`  | The JSON Schema to validate against         |

If a parameter arrives already decoded as an object or an array, it is
serialized back to JSON first.

#### Input must already be clean JSON

This plugin validates. It does **not** prepare input. `json_input` is passed
straight to `json.loads`, and anything that is not already valid JSON is
reported as `invalid_json` -- including a Markdown code fence around the JSON,
which is how LLMs usually wrap structured output.

That is deliberate. The tool emits only a validation verdict, never the parsed
JSON, so the variable the downstream nodes receive is still the original string.
Unwrapping a fence here would make `is_valid: true` describe a value nobody
downstream ever sees, turning a broken pipeline into a passing check.

So if your source is an LLM answer, extract the JSON before validating it. The
`invalid_json` error carries the line and column, which is usually enough to see
that the problem is a fence or a stray sentence rather than the JSON itself.

### Nesting depth

`jsonschema` validates a schema against its metaschema in pure Python and
consumes roughly ten interpreter frames per nesting level. CPython's default
recursion limit of 1000 therefore admits schemas up to ~95 levels deep, and
validates data up to ~100-200 levels deep against a recursive schema.

The plugin deliberately leaves that limit alone. Those ceilings are far beyond
anything an LLM emits or a human writes -- realistic schemas sit at 3-30 levels
-- and every input past the boundary is still answered with a structured error
rather than an exception. Raising the limit would buy capability nobody needs
while mutating process-global state, since `sys.setrecursionlimit()` affects
every task sharing the plugin process.

Beyond those boundaries, or for JSON documents too deep for the standard parser,
the tool still answers with a structured error instead of crashing:

| Situation                                        | `error_type`          |
|--------------------------------------------------|-----------------------|
| JSON data too deep for `json.loads`              | `invalid_json`        |
| JSON Schema too deep for `json.loads`            | `invalid_schema_json` |
| Schema too deep for metaschema checking          | `schema_error`        |
| Data too deep to validate, or a circular `$ref`  | `internal_error`      |

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
| `invalid_json`          | The data is not valid JSON (fences included)       | Fix the extraction, then retry         |
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

## The Schema Is Applied Exactly As Written

This plugin never rewrites your schema. Whatever it says is what gets enforced,
nothing more and nothing less. There is no global "strict mode" toggle, because
JSON Schema has no such concept either: the only way to reject undeclared
properties is `additionalProperties: false`, declared per object.

That is deliberate. A single switch that closed every object would override the
granular choices you already made -- closing one object and leaving another open
is a legitimate, precise decision, and a blanket toggle would destroy it. It
would also change semantics in non-obvious ways: closing both branches of an
`anyOf` makes `{"a": 1, "b": 2}` fail both, where it used to satisfy each.

So write the constraint where you want it:

```json
{
  "type": "object",
  "properties": { "name": { "type": "string" } },
  "additionalProperties": false
}
```

`additionalProperties` applies to properties not matched by `properties` or
`patternProperties`, so a closed object still accepts everything the schema
declares.

## Workflow Pattern

Extract the JSON from the model's answer first, then place the validator
between that step and the consumer, and branch on `is_valid`:

```
LLM node -> extract JSON -> JSON Schema Validator -> is_valid true  -> normal flow
                                               -> is_valid false -> error_type branch
                                                                            validation_failed -> retry with the error message
                                                                            invalid_json      -> fix the extraction, then retry
                                                                            schema_error      -> alert the workflow author
```

The extraction step is yours, not the plugin's: the validator reports whether the
string it was given is valid JSON, so a fenced answer has to be unwrapped before
it reaches the gate. A Code node with a small regex, or an LLM call asked to
return only the JSON, both do the job.

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
trade-off of the library choice.

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

## Icon

The plugin icon is the official JSON Schema logo
(<https://json-schema.org/logo-blue.svg>), centred on a light background.

## License

[MIT](./LICENSE)
