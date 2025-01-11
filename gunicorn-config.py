# gunicorn_config.py

# Server socket settings
bind = "0.0.0.0:10000"

# Worker processes
workers = 2
threads = 4

# Timeout settings
timeout = 120

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Process naming
proc_name = "taskbot_app"

# SSL (uncomment if using HTTPS)
# keyfile = "path/to/keyfile"
# certfile = "path/to/certfile"

# Maximum requests
max_requests = 1000
max_requests_jitter = 50

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL
secure_scheme_headers = {
    'X-FORWARDED-PROTOCOL': 'ssl',
    'X-FORWARDED-PROTO': 'https',
    'X-FORWARDED-SSL': 'on'
}
