"""Deployment-owned limits. The URL request cannot override safety settings."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UWT_", env_file=ROOT / ".env", extra="ignore")

    data_dir: Path = ROOT / "data"
    tools_dir: Path = ROOT / "tools"
    # Local/native development stays simple. Docker uses a separate worker process.
    worker_mode: Literal["inline", "external"] = "inline"
    frontend_dir: Path = ROOT / "frontend" / "dist"
    allowlist: str = "http://juice-shop:3000,http://dvwa:80"
    # Hackathon-safe default: every scan must target an explicitly approved origin.
    # Set UWT_REQUIRE_ALLOWLIST_ALL_SCANS=false only for a deployment that is
    # intentionally permitted to run passive/read-only checks on public sites.
    require_allowlist_all_scans: bool = True
    ollama_url: str = "http://ollama:11434"
    text_model: str = "qwen2.5:1.5b"
    vision_model: str = "qwen2.5vl:7b"
    ai_enabled: bool = True
    pull_vision: bool = True
    ai_timeout: float = Field(100, ge=5, le=300)
    ai_context: int = Field(8192, ge=2048, le=16384)
    ai_keep_alive: str = "1m"
    zap_url: str = "http://zap:8080"
    zap_api_key: str = "local-zap-change-me"
    proxy_advertised_host: str = "app"
    max_pages: int = Field(8, ge=1, le=30)
    max_depth: int = Field(2, ge=0, le=3)
    max_forms: int = Field(6, ge=0, le=12)
    max_tests_per_form: int = Field(4, ge=1, le=8)
    max_users: int = Field(4, ge=1, le=20)
    load_seconds: int = Field(10, ge=1, le=30)
    load_enabled: bool = True
    job_timeout: int = Field(2400, ge=30, le=3600)
    request_timeout: float = Field(25, ge=2, le=60)
    max_requests: int = Field(1500, ge=50, le=3000)
    proxy_rate: int = Field(15, ge=1, le=20)
    max_queue: int = Field(12, ge=1, le=50)
    max_body_bytes: int = Field(30_000_000, ge=4096, le=100_000_000)
    user_agent: str = "AI-Universal-Website-Tester/1.0 (authorized read-only scan)"
    nuclei_bin: str = "nuclei"
    chromium_path: str = ""
    node_bin: str = "node"

    # Authenticated testing settings
    auth_enabled: bool = False
    auth_login_url: str = ""
    auth_username: str = ""
    auth_password: str = ""
    auth_user_selector: str = ""
    auth_pass_selector: str = ""
    auth_submit_selector: str = ""
    auth_cookies: str = ""

    @property
    def approved_origins(self) -> list[str]:
        return [x.strip() for x in self.allowlist.split(",") if x.strip()]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tester.sqlite3"

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "jobs").mkdir(exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
