"""Legacy compatibility module mirroring app/__init__.py."""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from app.config import Config

db = SQLAlchemy()


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

    return app
