from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GTNH_", env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    request_interval: float = Field(default=2.0, ge=1.0)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    context_tokens: int = Field(default=5000, ge=500, le=20000)
    history_tokens: int = Field(default=800, ge=0, le=4000)
    output_tokens: int = Field(default=1000, ge=200, le=8000)
    retrieval_limit: int = Field(default=8, ge=1, le=30)
    search_rounds: int = Field(default=2, ge=0, le=3)
    input_price: float | None = Field(default=None, ge=0)
    cached_input_price: float | None = Field(default=None, ge=0)
    output_price: float | None = Field(default=None, ge=0)
    price_date: str = ""
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY", repr=False)
    openai_model: str = Field(default="gpt-4.1-mini", validation_alias="OPENAI_MODEL")

    def prepare(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self
