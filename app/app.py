
from flask import Flask
from app.blueprints.main import main_bp

def create_app():
    app = Flask(__name__)
    app.register_blueprint(main_bp)
    return app

app = create_app()
