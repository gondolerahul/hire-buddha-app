from pydantic_settings import BaseSettings, SettingsConfigDict

class GatewaySettings(BaseSettings):
    BACKEND_URL: str = "http://app:8000"
    REDIS_URL: str = "redis://redis:6379"
    RATE_LIMIT: str = "100/minute"
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = GatewaySettings()
