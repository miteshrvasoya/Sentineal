from app.config import get_settings
from app.llm.providers.openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    def __init__(self, client=None, key: str | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__("openai", key if key is not None else get_settings().openai_api_key, None, True, client)
