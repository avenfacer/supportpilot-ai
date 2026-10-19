from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ProviderName = Literal["fake", "openai"]

# Default relevance thresholds per embedding provider. Cosine similarity distributions differ
# between providers, so a single global constant would be wrong for one of them. The fake value
# comes from the threshold sweep in evals/README.md; the OpenAI value is a starting point to be
# confirmed with `scripts/run_evals.py --live`.
DEFAULT_MIN_SCORE: dict[str, float] = {"fake": 0.15, "openai": 0.3}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    app_name: str = "SupportPilot AI"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://supportpilot:supportpilot@localhost:5433/supportpilot"

    llm_provider: ProviderName = "fake"
    embedding_provider: ProviderName = "fake"
    openai_api_key: SecretStr | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    llm_timeout_seconds: float = Field(default=20.0, gt=0)
    embedding_timeout_seconds: float = Field(default=20.0, gt=0)

    order_api_timeout_seconds: float = Field(default=3.0, gt=0)
    order_api_max_attempts: int = Field(default=2, ge=1, le=3)
    mock_order_failure_mode: Literal["none", "timeout", "unavailable"] = "none"

    knowledge_base_dir: Path = PROJECT_ROOT / "data" / "knowledge_base"
    chunk_size: int = Field(default=800, ge=200)
    chunk_overlap: int = Field(default=120, ge=0)
    retrieval_top_k: int = Field(default=4, ge=1, le=20)
    retrieval_min_score: float | None = Field(default=None, ge=-1.0, le=1.0)

    enable_demo_auth: bool = True
    enable_admin_endpoints: bool = False
    admin_token: SecretStr | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        uses_openai = "openai" in (self.llm_provider, self.embedding_provider)
        if uses_openai and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when an OpenAI provider is selected")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.enable_admin_endpoints and not self.admin_token:
            raise ValueError("ADMIN_TOKEN is required when ENABLE_ADMIN_ENDPOINTS=true")
        return self

    @property
    def effective_min_score(self) -> float:
        if self.retrieval_min_score is not None:
            return self.retrieval_min_score
        return DEFAULT_MIN_SCORE[self.embedding_provider]


@lru_cache
def get_settings() -> Settings:
    return Settings()
