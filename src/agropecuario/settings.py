"""Configuración global tipada.

`get_settings()` es el único punto de acceso — cacheado para evitar releer .env.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
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

    # Investigación web con la búsqueda nativa de OpenAI (web search). Usa la misma
    # OPENAI_API_KEY; si falta o falla, el lookup degrada sin romper el flujo.
    web_lookup_enabled: bool = Field(default=True, alias="WEB_LOOKUP_ENABLED")
    web_search_model: str = Field(default="gpt-4o", alias="WEB_SEARCH_MODEL")

    # Google
    google_client_secrets: Path = Field(
        default=Path("./secrets/client_secret.json"), alias="GOOGLE_CLIENT_SECRETS"
    )
    google_token_path: Path = Field(
        default=Path("./secrets/token.json"), alias="GOOGLE_TOKEN_PATH"
    )

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

    # Límites del texto que se manda al LLM. El contexto de gpt-4o son ~128k
    # tokens (~500k caracteres): sin tope, un hilo con varios PDF largos lo
    # revienta y el run falla entero. Se cuenta en caracteres, no en tokens, para
    # no depender del tokenizador.
    max_chars_por_adjunto: int = Field(default=50_000, alias="MAX_CHARS_POR_ADJUNTO")
    max_chars_total: int = Field(default=200_000, alias="MAX_CHARS_TOTAL")

    # Manual de servicios Finagro (RAG): PDF fuente + índice vectorial construido.
    manual_pdf_path: Path = Field(
        default=Path("./config/manual_servicios.pdf"), alias="MANUAL_PDF_PATH"
    )
    manual_index_dir: Path = Field(
        default=Path("./config/manual_index"), alias="MANUAL_INDEX_DIR"
    )

    @property
    def openai_key(self) -> SecretStr:
        """La llave como la piden los clientes de langchain.

        `ChatOpenAI` y `OpenAIEmbeddings` tipan `api_key` como `SecretStr`: un
        `str` pelado funciona en runtime pero mypy lo marca, y envolverlo evita
        además que la llave aparezca en el `repr` del cliente. Se convierte en un
        único sitio en vez de en los cinco que la usan.
        """
        return SecretStr(self.openai_api_key)

    def ensure_dirs(self) -> None:
        for p in (self.temp_dir, self.output_dir, self.db_path.parent):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
