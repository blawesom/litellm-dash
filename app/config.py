import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present
BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

class Settings:
    LITELLM_BASE_URL: str = os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4001").rstrip("/")
    LITELLM_MASTER_KEY: str = os.getenv("LITELLM_MASTER_KEY", "sk-litellm-master-secret-key")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "default-dev-secret-key-change-in-production")
    SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "litellm_dash_session")
    SESSION_MAX_AGE_DAYS: int = int(os.getenv("SESSION_MAX_AGE_DAYS", "7"))
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")
    ALLOW_MOCK_FALLBACK: bool = os.getenv("ALLOW_MOCK_FALLBACK", "false").lower() in ("true", "1", "yes")

settings = Settings()
