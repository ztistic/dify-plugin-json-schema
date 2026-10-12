# Privacy Policy for JSON Schema Plugin

**Last Updated: October 12, 2026**

## Overview

This privacy policy explains how the JSON Schema Plugin for Dify ("the
Plugin") handles data when you use it to validate JSON documents against a
JSON Schema.

## Data Collection

The Plugin does **not** collect, store, log, or transmit any personal data.

The Plugin only processes the following data during operation, solely to
perform its function:

1. **Input data**: the JSON string and the JSON Schema string you provide to
   the validation tool — used only to produce the validation result for the
   current request.

## Data Processing

- Validation happens entirely in-memory inside the Plugin's execution
  environment.
- Both inputs are parsed, validated, and discarded within the same request.
- The Plugin keeps no copy of any data after the operation completes.
- Remote `$ref` references are intentionally not fetched: no outbound request
  is ever made as a result of validating a schema.

## Data Storage

- The Plugin does not maintain any persistent storage of user data.
- No database, file, or cache is written by the Plugin.

## Third-party Services

The Plugin does **not** call any third-party API and does **not** send data to
any external service. It requires no network access, no credentials, and no
API keys.

## Data Transmission

- The Plugin makes no outbound network connections.
- All data stays within your Dify deployment.

## Data Retention

- The Plugin does not retain user data beyond the duration of a single tool
  invocation. Error messages returned to the workflow may echo back fragments
  of the submitted JSON or schema, and they live only inside your own Dify
  workflow run.

## User Rights

As a user, you have the right to:

- Know what data the Plugin processes (this document)
- Audit the full source code, which is open and publicly available

## Contact

For questions about this policy or our data practices, open an issue in the
[JSON Schema Plugin Repository](https://github.com/ztistic/dify-plugin-json-schema).
