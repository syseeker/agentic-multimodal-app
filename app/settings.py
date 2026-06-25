"""Runtime settings, loaded from environment (.env). See .env.example."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Hardware
    gpu_profile: str = "rtx6000"

    # Model tags (verify latest on HF)
    text_model: str = "Qwen/Qwen3-14B"
    vlm_model: str = "Qwen/Qwen3-VL-8B-Instruct"
    audio_model: str = "MERaLiON/MERaLiON-3-10B"
    quant: str = "fp8"
    max_model_len: int = 16384

    # Serving endpoints (OpenAI-compatible vLLM)
    text_base_url: str = "http://serving-text:8001/v1"
    vlm_base_url: str = "http://serving-vlm:8002/v1"
    audio_base_url: str = "http://serving-audio:8003/v1"
    serving_api_key: str = "local-dev-key"

    # Served model names (match serving/ --served-model-name)
    text_served: str = "text"
    vlm_served: str = "vlm"
    audio_served: str = "audio"

    # Data stores
    falkordb_host: str = "falkordb"
    falkordb_port: int = 6379
    milvus_uri: str = "http://milvus:19530"
    vector_backend: str = "milvus"  # milvus | chroma
    chroma_path: str = "/data/chroma"

    # Agent
    agent_engine: str = "deepagents"  # deepagents | hermes
    agent_config: str = "app/config/config_sherlock.yml"

    # App
    app_port: int = 8000

    # Observability (P1)
    otel_exporter_otlp_endpoint: str = "http://phoenix:6006/v1/traces"
    enable_tracing: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
