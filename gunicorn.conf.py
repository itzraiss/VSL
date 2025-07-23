# Gunicorn configuration for production deployment
import multiprocessing
import os

# Server socket
bind = f"0.0.0.0:{os.environ.get('PORT', 7860)}"
backlog = 2048

# Worker processes
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)  # Cap at 4 workers
worker_class = "sync"
worker_connections = 1000
timeout = 120  # Increased for transcription processing
keepalive = 2

# Performance tuning
max_requests = 1000
max_requests_jitter = 50
preload_app = True

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "vsl-transcription-app"

# Memory management
worker_tmp_dir = "/dev/shm"  # Use RAM for temporary files

# SSL (if needed)
# keyfile = None
# certfile = None

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

def post_fork(server, worker):
    """Called after a worker has been forked"""
    server.log.info(f"Worker spawned (pid: {worker.pid})")

def pre_fork(server, worker):
    """Called before a worker is forked"""
    pass

def when_ready(server):
    """Called when the server is started"""
    server.log.info("Server is ready. Spawning workers")

def worker_int(worker):
    """Called when a worker receives an INT signal"""
    worker.log.info("Worker received INT signal")

def on_exit(server):
    """Called when the server is stopped"""
    server.log.info("Server is shutting down")