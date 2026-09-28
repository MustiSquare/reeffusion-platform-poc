from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    survey_upload_limit_mb: int = 2048
    survey_decompressed_limit_mb: int = 16384
    project_name: str = "ReefFusion Platform"
    database_url: str = "postgresql+psycopg://reefusion:reefusion@postgres:5432/reefusion"
    redis_url: str = "redis://redis:6379/0"
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "reefusion"
    s3_secure: bool = False
    backend_cors_origins: str = "http://localhost:3000"
    ai_provider: str = "local"
    ai_enabled: bool = True
    auth_enabled: bool = False
    auth_admin_token: str = "local-admin-token"
    auth_editor_token: str = "local-editor-token"
    processed_export_dir: str = str(Path(__file__).resolve().parents[3] / "test_data")

settings = Settings()
