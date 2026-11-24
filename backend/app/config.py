"""Application settings, loaded from environment / .env. Secrets never logged."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    database_url: str = f"sqlite:///{ROOT / 'data' / 'quantlens.db'}"
    timezone: str = "Asia/Kolkata"
    log_level: str = "INFO"
    default_watchlist: str = "RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK,SBIN,BHARTIARTL,ITC,LT,HINDUNILVR"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    price_cache_ttl_seconds: int = 300

    # Optional keys (later phases). Never exposed by the API.
    angel_api_key: str = Field(default="", repr=False)
    angel_client_code: str = Field(default="", repr=False)
    angel_pin: str = Field(default="", repr=False)
    angel_totp_secret: str = Field(default="", repr=False)

    finnhub_key: str = Field(default="", repr=False)
    marketaux_key: str = Field(default="", repr=False)
    alphavantage_key: str = Field(default="", repr=False)
    newsapi_key: str = Field(default="", repr=False)

    anthropic_api_key: str = Field(default="", repr=False)
    gemini_api_key: str = Field(default="", repr=False)
    openai_api_key: str = Field(default="", repr=False)
    groq_api_key: str = Field(default="", repr=False)
    ollama_base_url: str = ""
    llm_default_provider: str = ""
    llm_daily_token_budget: int = 200_000
    llm_daily_usd_budget: float = 1.0
    llm_enable_forward_only_features: bool = True

    @property
    def watchlist(self) -> list[str]:
        return [s.strip().upper() for s in self.default_watchlist.split(",") if s.strip()]

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
