"""应用配置：全部通过环境变量 / .env 注入。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 基础 ----
    app_name: str = "WHOOP AI Analyst"
    database_url: str = f"sqlite:///{ROOT_DIR / 'data' / 'whoop_analyst.db'}"
    timezone: str = "Asia/Shanghai"
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---- WHOOP OAuth ----
    whoop_client_id: str = ""
    whoop_client_secret: str = ""
    whoop_redirect_uri: str = "http://localhost:8000/api/whoop/auth/callback"
    whoop_api_base: str = "https://api.prod.whoop.com/developer"
    whoop_auth_url: str = "https://api.prod.whoop.com/oauth/oauth2/auth"
    whoop_token_url: str = "https://api.prod.whoop.com/oauth/oauth2/token"
    whoop_initial_backfill_days: int = 365

    # ---- LLM ----
    # none: 不调用大模型，使用规则引擎生成中文解读
    # openai_compatible: DeepSeek / 通义千问 / Kimi / 智谱 / OpenAI 等兼容接口
    # anthropic: Claude
    llm_provider: str = "none"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    anthropic_enable_fallbacks: bool = True

    agent_max_steps: int = 8

    # ---- 定时任务 ----
    enable_scheduler: bool = False
    daily_sync_hour: int = 9

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
