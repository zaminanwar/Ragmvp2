"""Application configuration using pydantic-settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    app_name: str = "EnterpriseRAG"
    app_env: str = "development"
    app_debug: bool = True
    secret_key: str = "change-me-to-a-secure-random-string"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Database
    database_url: str = "postgresql+asyncpg://raguser:ragpass@localhost:5432/ragdb"
    database_sync_url: str = "postgresql://raguser:ragpass@localhost:5432/ragdb"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "rag-documents"
    minio_use_ssl: bool = False

    # Elasticsearch
    elasticsearch_url: str = "http://localhost:9200"

    # LLM Providers
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    ollama_base_url: str = "http://localhost:11434"

    # Google Gemini / Vertex AI
    google_api_key: Optional[str] = None
    google_cloud_project: Optional[str] = None
    google_cloud_location: str = "us-central1"
    google_application_credentials: Optional[str] = None
    google_service_account_json: Optional[str] = None

    # Default LLM
    default_llm_provider: str = "openai"
    default_llm_model: str = "gpt-4o"
    default_temperature: float = 0.1

    # Embeddings
    default_embedding_provider: str = "openai"
    default_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Vector Store
    default_vector_store: str = "pgvector"

    # Document Processing
    max_upload_size_mb: int = 100
    supported_file_types: str = "pdf,docx,txt,md,csv,xlsx,pptx,html,json"
    chunk_size: int = 512
    chunk_overlap: int = 50

    # Auth
    jwt_secret_key: str = "change-me-jwt-secret"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 1440
    allow_registration: bool = True

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Telemetry
    enable_telemetry: bool = False
    otel_exporter_endpoint: str = "http://localhost:4317"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def supported_file_type_list(self) -> list[str]:
        return [t.strip() for t in self.supported_file_types.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
