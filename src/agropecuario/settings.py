"""Configuración global tipada.

`get_settings()` es el único punto de acceso — cacheado para evitar releer .env.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # OpenAI
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    openai_model_mini: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL_MINI")
    embedding_model: str = Field(
        default="text-embedding-3-small", alias="EMBEDDING_MODEL"
    )

    # Investigación web (Tavily) para apoyar al code_resolver con la razón social.
    # Si falta la llave, el lookup degrada (se desactiva) sin romper el flujo.
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    web_lookup_enabled: bool = Field(default=True, alias="WEB_LOOKUP_ENABLED")

    # Google
    google_client_secrets: Path = Field(
        default=Path("./secrets/client_secret.json"), alias="GOOGLE_CLIENT_SECRETS"
    )
    google_token_path: Path = Field(
        default=Path("./secrets/token.json"), alias="GOOGLE_TOKEN_PATH"
    )
    drive_output_folder_id: str = Field(default="", alias="DRIVE_OUTPUT_FOLDER_ID")

    # Gmail
    gmail_monitored_label: str = Field(default="INBOX", alias="GMAIL_MONITORED_LABEL")
    gmail_query_filter: str = Field(default="is:unread", alias="GMAIL_QUERY_FILTER")
    # Etiqueta que el analista pone para disparar el procesamiento del hilo.
    gmail_label_trigger: str = Field(default="bot", alias="GMAIL_LABEL_TRIGGER")
    # Etiqueta que el agente añade al hilo cuando termina (para no reprocesarlo).
    gmail_label_done: str = Field(default="bot-procesado", alias="GMAIL_LABEL_DONE")

    # App
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    db_path: Path = Field(default=Path("./data/agropecuario.sqlite"), alias="DB_PATH")
    temp_dir: Path = Field(default=Path("./data/tmp"), alias="TEMP_DIR")
    output_dir: Path = Field(default=Path("./data/output"), alias="OUTPUT_DIR")

    # UI
    ui_host: str = Field(default="127.0.0.1", alias="UI_HOST")
    ui_port: int = Field(default=8000, alias="UI_PORT")

    # Rutas de config
    rules_path: Path = Field(default=Path("./config/rules.yaml"), alias="RULES_PATH")
    template_path: Path = Field(default=Path("./config/template.yaml"), alias="TEMPLATE_PATH")

    # Manual de servicios Finagro (RAG): PDF fuente + índice vectorial construido.
    manual_pdf_path: Path = Field(
        default=Path("./config/manual_servicios.pdf"), alias="MANUAL_PDF_PATH"
    )
    manual_index_dir: Path = Field(
        default=Path("./config/manual_index"), alias="MANUAL_INDEX_DIR"
    )

    def ensure_dirs(self) -> None:
        for p in (self.temp_dir, self.output_dir, self.db_path.parent):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
