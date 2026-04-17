from app import create_app
from app.scheduler import start_scheduler

app = create_app()
start_scheduler(app)
