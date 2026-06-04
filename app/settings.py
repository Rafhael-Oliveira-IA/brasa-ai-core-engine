from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Brasa AI Core Lite"
    environment: str = "dev"
    log_level: str = "INFO"
    frontend_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    data_dir: Path = BASE_DIR / "data"
    brasa_runtime_root: Path = BASE_DIR / ".brasa" / "runtime"
    brasa_cognition_root: Path = BASE_DIR / ".brasa" / "cognition"
    brasa_calibration_root: Path = BASE_DIR / ".brasa" / "calibration"
    brasa_runtime_sessions_dir: Path = BASE_DIR / ".brasa" / "runtime" / "sessions"
    brasa_runtime_traces_dir: Path = BASE_DIR / ".brasa" / "runtime" / "traces"
    brasa_runtime_context_dir: Path = BASE_DIR / ".brasa" / "runtime" / "temporary_context"
    calibration_failures_dir: Path = BASE_DIR / ".brasa" / "calibration" / "failures"
    calibration_heuristics_dir: Path = BASE_DIR / ".brasa" / "calibration" / "heuristics"
    calibration_weights_dir: Path = BASE_DIR / ".brasa" / "calibration" / "weights"
    calibration_profiles_dir: Path = BASE_DIR / ".brasa" / "calibration" / "ranking_profiles"
    sqlite_path: Path = BASE_DIR / "data" / "memory.db"
    trace_file: Path = BASE_DIR / "data" / "traces.jsonl"
    reflection_dir: Path = BASE_DIR / "data" / "reflection_reports"
    evaluation_dir: Path = BASE_DIR / "data" / "evaluations"
    knowledge_dir: Path = BASE_DIR / "data" / "knowledge"
    knowledge_state_file: Path = BASE_DIR / "data" / "knowledge" / "state.json"
    knowledge_max_file_bytes: int = 300000
    knowledge_include_extensions: str = ".py,.lua,.md,.txt,.json,.xml,.yaml,.yml,.toml,.ini,.ts,.tsx,.js,.jsx,.cs,.java,.kt,.go,.rs,.cpp,.c,.h"
    action_workspace_root: Path = BASE_DIR
    action_backup_dir: Path = BASE_DIR / ".brasa" / "runtime" / "action_backups"
    action_blocked_paths: str = (
        ".git,node_modules,.brasa,data/evaluations,data/knowledge,data/reflection_reports,data/traces.jsonl,data/memory.db"
    )
    action_allow_delete: bool = False
    action_max_file_bytes: int = 500000
    action_model_assist_enabled: bool = True
    action_model_assist_tier: str = "flash"

    local_model_name: str = "local-lite-v1"

    alibaba_api_key: str | None = None
    alibaba_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    alibaba_region_base_urls: str = ""
    alibaba_max_retries: int = 2
    alibaba_retry_backoff_seconds: float = 0.35
    alibaba_model_flash: str = "qwen-turbo-latest"
    alibaba_model_plus: str = "qwen-plus-latest"
    alibaba_model_max: str = "qwen-max-latest"
    alibaba_embedding_enabled: bool = True
    alibaba_embedding_model: str = "text-embedding-v4"
    alibaba_embedding_timeout_seconds: int = 25
    alibaba_embedding_max_batch_size: int = 10
    alibaba_embedding_cache_file: Path = BASE_DIR / "data" / "knowledge" / "embeddings_cache.json"

    max_escalation_depth: int = 3
    request_budget_usd: float = 0.20
    chat_force_alibaba_response: bool = True
    chat_force_alibaba_ignore_budget: bool = True
    chat_local_assist_enabled: bool = True
    chat_local_assist_max_chars: int = 1400
    chat_auto_reingest_on_weak_context: bool = True
    chat_auto_reingest_min_selected_context: int = 2
    chat_auto_reingest_cooldown_seconds: int = 120

    enable_reflection_scheduler: bool = False
    reflection_interval_minutes: int = 1440

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.reflection_dir.mkdir(parents=True, exist_ok=True)
    settings.evaluation_dir.mkdir(parents=True, exist_ok=True)
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    settings.knowledge_state_file.parent.mkdir(parents=True, exist_ok=True)
    settings.alibaba_embedding_cache_file.parent.mkdir(parents=True, exist_ok=True)
    settings.trace_file.parent.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    settings.brasa_runtime_root.mkdir(parents=True, exist_ok=True)
    settings.brasa_cognition_root.mkdir(parents=True, exist_ok=True)
    settings.brasa_calibration_root.mkdir(parents=True, exist_ok=True)
    settings.brasa_runtime_sessions_dir.mkdir(parents=True, exist_ok=True)
    settings.brasa_runtime_traces_dir.mkdir(parents=True, exist_ok=True)
    settings.brasa_runtime_context_dir.mkdir(parents=True, exist_ok=True)
    settings.calibration_failures_dir.mkdir(parents=True, exist_ok=True)
    settings.calibration_heuristics_dir.mkdir(parents=True, exist_ok=True)
    settings.calibration_weights_dir.mkdir(parents=True, exist_ok=True)
    settings.calibration_profiles_dir.mkdir(parents=True, exist_ok=True)
    settings.action_workspace_root.mkdir(parents=True, exist_ok=True)
    settings.action_backup_dir.mkdir(parents=True, exist_ok=True)
    return settings
