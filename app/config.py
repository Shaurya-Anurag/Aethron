from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "AETHRON"
    database_path: str = "./aethron.db"
    bifrost_base_url: str = ""
    bifrost_api_key: str = ""
    bifrost_model: str = ""
    tavily_api_key: str = ""
    nmap_path: str = "nmap"
    max_scan_targets: int = 32
    scan_timeout_seconds: int = 180
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

settings = Settings()
