"""Centralized configuration loaded from environment variables."""

import os


class Config:
    """Default Flask configuration for local and Docker environments."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://timetracker:timetracker_pass@db:5432/timetracker"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
