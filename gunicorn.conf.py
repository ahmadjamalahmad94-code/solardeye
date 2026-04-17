from app.scheduler import start_scheduler

workers = 1
threads = 2

def post_fork(server, worker):
    try:
        from wsgi import app
        start_scheduler(app)
        server.log.info('Scheduler started in worker pid=%s', worker.pid)
    except Exception as exc:
        server.log.exception('Failed to start scheduler in worker: %s', exc)
