from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .llm import normalize_host


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GTNH_", env_file=".env", extra="ignore", populate_by_name=True
    )
    data_dir: Path = Path("data")
    request_interval: float = Field(default=2.0, ge=1.0)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    context_tokens: int = Field(default=5000, ge=500, le=20000)
    history_tokens: int = Field(default=800, ge=0, le=4000)
    output_tokens: int = Field(default=1000, ge=200, le=8000)
    retrieval_limit: int = Field(default=8, ge=1, le=30)
    search_rounds: int = Field(default=2, ge=0, le=3)
    # Local inference through Ollama. There is no remote or paid fallback.
    ollama_host: str = Field(
        default="http://127.0.0.1:11434", validation_alias=AliasChoices("GTNH_OLLAMA_HOST", "OLLAMA_HOST")
    )
    llm_model: str = "qwen3.5:4b"
    num_ctx: int = Field(default=8192, ge=2048, le=131072)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    keep_alive: str = "30m"
    llm_timeout: float = Field(default=180.0, ge=10.0)
    # False keeps chat responsive; models without a thinking mode simply ignore it.
    think: bool | None = False

    @field_validator("ollama_host")
    @classmethod
    def _host(cls, value):
        return normalize_host(value)

    def prepare(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self
