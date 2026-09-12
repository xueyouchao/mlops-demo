"""Application configuration for the API service."""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_url: str = "postgresql://postgres:postgres@postgres:5432/mlplatform"
    jwt_secret: str = "change-me-in-prod"
    auth_token_ttl_minutes: int = 15
    mlflow_tracking_uri: str = "http://mlflow:5000"
    temporal_host: str = "temporal"
    temporal_port: int = 7233
    serving_url: str = "http://serving:8001"
    internal_service_token: str = "change-me-internal"
    sentry_dsn: str = ""
    sentry_env: str = "development"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
