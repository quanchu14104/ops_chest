from datetime import date
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_ignore_empty: "SIM_TODAY=" (de trong theo .env.example) phai hieu la "khong dat", khong phai loi
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite:///./ops_chest.db"

    # LLM: bat ky endpoint OpenAI-compatible nao (OpenAI, OpenRouter, DeepSeek, Ollama, ...)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_stream: bool = True
    # Xin usage (so token) trong stream. Tat neu provider bao loi "stream_options" khong hop le.
    llm_stream_usage: bool = True
    llm_max_tool_rounds: int = 8
    llm_temperature: float = 0.2
    # LLM phu (fallback): dung khi LLM chinh loi 429/5xx/mat ket noi truoc khi tra loi duoc gi.
    # Ten bien khong phan biet hoa thuong: LLM_BASE_URL_FALLBACK == LLM_BASE_URL_fallback.
    llm_base_url_fallback: str = ""
    llm_api_key_fallback: str = ""
    llm_model_fallback: str = ""
    # LLM chinh bi "nghi" bao lau sau khi het han muc (giay)
    llm_cooldown_seconds: int = 120
    llm_cooldown_daily_limit_seconds: int = 900

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "dathang@opschest-demo.test"

    store_name: str = "Cửa hàng Tiện Lợi Ops Chest Demo"
    store_address: str = "123 Nguyễn Văn Cừ, Q.5, TP.HCM"
    store_phone: str = "028 0000 0000"

    # Ngay nghiep vu. De trong = ngay that (Asia/Ho_Chi_Minh). Dat co dinh de demo on dinh.
    sim_today: date | None = None
    timezone: str = "Asia/Ho_Chi_Minh"

    secret_key: str = "change-me-in-.env"
    token_ttl_hours: int = 12

    pdf_font_path: str | None = None
    pdf_output_dir: str = "./generated"
    enable_scheduler: bool = True
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
