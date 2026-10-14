"""Configuração carregada de variáveis de ambiente (spec §9)."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/consultas"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"

    # Sem valor padrão de propósito: a aplicação não sobe com uma chave embutida no código.
    api_key: SecretStr
    rate_limit_por_minuto: int = Field(default=60, ge=1)

    documento_validar_dv: bool = True

    externo_url: str = "http://localhost:9000"
    externo_timeout_conexao_s: float = Field(default=2.0, gt=0)
    externo_timeout_leitura_s: float = Field(default=3.0, gt=0)

    retry_max_tentativas: int = Field(default=5, ge=1)
    retry_base_segundos: float = Field(default=2.0, gt=0)
    retry_teto_segundos: float = Field(default=60.0, gt=0)

    worker_concorrencia: int = Field(default=2, ge=1)
    tarefa_rate_limit: str = "10/s"


@lru_cache
def get_settings() -> Settings:
    return Settings()
