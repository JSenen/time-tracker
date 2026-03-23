"""Application factory and shared SQLAlchemy instance."""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

from app.config import Config

db = SQLAlchemy()


def ensure_schema_updates():
    """Apply lightweight schema updates for installations without migrations."""
    inspector = inspect(db.engine)

    if "projects" not in inspector.get_table_names():
        return

    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    if "color" not in project_columns:
        db.session.execute(text("ALTER TABLE projects ADD COLUMN color VARCHAR(20)"))
        db.session.commit()


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        # Import inside the app context so models and routes see the initialized app/db.
        from app import models
        from app.routes import main

        app.register_blueprint(main)
        # Keep schema creation simple while the project does not use migrations yet.
        db.create_all()
        ensure_schema_updates()

    return app
