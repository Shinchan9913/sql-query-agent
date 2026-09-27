"""Application settings, loaded from environment variables or the repo-level .env."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_path: Path = Path("database/sample.db")
    data_dir: Path = Path("data")  # conversation checkpoints and thread list
    cors_origins: list[str] = ["http://localhost:5173"]

    # LLMs, in LangChain `provider:model` form
    llm_model: str = "nvidia:openai/gpt-oss-20b"
    llm_fallback_model: str | None = None
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 60.0

    # Agent loop limits
    max_tool_calls: int = 4
    max_sql_retries: int = 2
    max_input_chars: int = 4000
    history_turns: int = 6

    # Query runner (user-initiated execution)
    max_result_rows: int = 500
    query_timeout_seconds: float = 5.0

    # Agent data tools
    max_probe_rows: int = 20
    max_column_values: int = 25

    @property
    def resolved_database_path(self) -> Path:
        return _resolve(self.database_path)

    @property
    def resolved_data_dir(self) -> Path:
        return _resolve(self.data_dir)


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


@lru_cache
def get_settings() -> Settings:
    # LangChain provider packages read API keys (GOOGLE_API_KEY, NVIDIA_API_KEY)
    # from the environment, so expose .env there too. Real env vars take precedence.
    load_dotenv(REPO_ROOT / ".env", override=False)
    return Settings()
