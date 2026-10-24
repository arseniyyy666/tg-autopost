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


settings = Settings()
