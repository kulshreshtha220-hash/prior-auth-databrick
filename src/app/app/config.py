"""Backend settings. Databricks runtime settings live in pa_core.config."""
import os


class Settings:
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    # Same-origin in Databricks Apps; only used for local `next dev`.


settings = Settings()
