from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://phantom:phantom@localhost:5432/phantom"
    REDIS_URL: str = "redis://localhost:6379/0"
    OLLAMA_URL: str = "http://localhost:11434"

    JWT_SECRET: str = "change_me_secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TTL_MINUTES: int = 10080   # 7 days
    JWT_REFRESH_TTL_DAYS: int = 30

    GOOGLE_CLIENT_ID: str = ""
    ENV: str = "development"


settings = Settings()
