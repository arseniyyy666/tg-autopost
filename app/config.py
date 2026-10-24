from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str
    bot_token: str
    webapp_url: str = ""
    run_bot: bool = True
    # How long a Mini App initData signature is accepted (seconds).
    initdata_max_age: int = 86400

    # Telegram API credentials of the service (my.telegram.org).
    api_id: int
    api_hash: str
    # "version:base64key,..." for AES-GCM encryption of stored sessions.
    session_keys: str

    # Account connection limits (will move to the plans module later).
    max_accounts_per_user: int = 1
    login_ttl_seconds: int = 600
    login_max_code_attempts: int = 5
    login_max_password_attempts: int = 5
    login_max_starts: int = 3
    login_start_window_seconds: int = 600


settings = Settings()
