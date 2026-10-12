from typing import Any

from dify_plugin import ToolProvider


class JsonSchemaToolProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        # Validation runs fully locally; there are no credentials to check.
        return
