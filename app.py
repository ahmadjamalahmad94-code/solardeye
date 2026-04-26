import os
from app import create_app
from app.scheduler import start_scheduler

app = create_app()

if __name__ == "__main__":
    start_scheduler(app)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
