import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://timetracker:timetracker_pass@db:5432/timetracker"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False