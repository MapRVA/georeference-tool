"""
Django settings for yesterdays project.
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

LOCAL_DEV = os.getenv("LOCAL_DEV", "False").lower() in ("true", "1", "yes")

# Set DEBUG to True if LOCAL_DEV is True (unless explicitly overwritten)
if LOCAL_DEV and os.getenv("DJANGO_DEBUG") is None:
    DEBUG = True
else:
    DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in ("true", "1", "yes")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = (
            "django-insecure-ydhsy&ts2zv0tq9b#nbtsjiga1cbo39hgo0vzlj9y!8#c+t*+2"
        )
    else:
        raise ValueError("DJANGO_SECRET_KEY or DEBUG environment variable must be set")

# Allow hosts from environment variable or use defaults
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Proxy settings for Cloudflare tunnel
# Tell Django to trust the X-Forwarded-Proto header from the proxy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# CORS settings
CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "True").lower() in (
    "true",
    "1",
    "yes",
)

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.postgres",
    "corsheaders",
    "django_vite",
    "osm_auth",
    "subjects",
    "images",
    "maps",
    "activity",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "osm_auth.middleware.OSMAuthenticationMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "yesterdays.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "osm_auth.context_processors.osm_auth",
                "images.context_processors.site_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "yesterdays.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
# Use SQLite for local development, PostgreSQL for production
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.getenv("PG_DBNAME", "georef"),
        "USER": os.getenv("PG_USER", "django_user"),
        "PASSWORD": os.getenv("PG_PASSWORD", ""),
        "HOST": os.getenv("PG_HOST", "georef-db-rw"),
        "PORT": os.getenv("PG_PORT", "5432"),
        "OPTIONS": {
            "sslmode": os.getenv("PG_SSL_MODE", "prefer"),
        },
    }
}

# Read database password from mounted secret if available
db_password_file = os.getenv("DB_PASSWORD_FILE", "/etc/georef-db/password")
if os.path.exists(db_password_file):
    with open(db_password_file, "r") as f:
        DATABASES["default"]["PASSWORD"] = f.read().strip()


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "UTC")

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/
STATIC_URL = "static/"
# In production: STATIC_ROOT is where collectstatic puts files and where they're served from
# In development: STATICFILES_DIRS tells Django where to find static files
if DEBUG:
    STATIC_ROOT = None  # Not used in development
    STATICFILES_DIRS = [
        BASE_DIR / "static",  # Vite build output (for production builds during dev)
    ]
else:
    STATIC_ROOT = BASE_DIR / "static"  # Vite outputs here, Whitenoise serves from here
    STATICFILES_DIRS = []  # No additional dirs in production

# Whitenoise configuration
# In development, use default storage so Vite rebuilds are picked up immediately
# In production, use CompressedManifestStaticFilesStorage for caching/compression
if DEBUG:
    WHITENOISE_AUTOREFRESH = True
else:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Django Vite configuration
DJANGO_VITE = {
    "default": {
        "dev_mode": os.getenv("DJANGO_VITE_DEV_MODE", "False").lower() == "true",
        "dev_server_host": "localhost",
        "dev_server_port": 5173,
        "manifest_path": BASE_DIR / "static" / "manifest.json",
    }
}

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery Configuration (RabbitMQ)
CELERY_BROKER_URL = os.getenv(
    "CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"
)
CELERY_RESULT_BACKEND = None  # Results stored in Image.thumbnail field directly
CELERY_TASK_IGNORE_RESULT = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 300  # 5 minutes max per task
CELERY_TASK_SOFT_TIME_LIMIT = 240  # Soft limit at 4 minutes

# RabbitMQ-specific settings
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_HEARTBEAT = 10  # Heartbeat interval in seconds
CELERY_BROKER_POOL_LIMIT = 10  # Connection pool size

# Queue routing configuration
CELERY_TASK_ROUTES = {
    # Thumbnail generation goes to background queue
    "images.tasks.generate_thumbnail_for_image": {"queue": "background"},
    "images.tasks.generate_thumbnails_batch": {"queue": "background"},
    # Metadata refresh tasks go to background queue
    "subjects.tasks.refresh_next_wikidata_item": {"queue": "background"},
    "subjects.tasks.refresh_next_osm_element": {"queue": "background"},
}

# Metadata refresh intervals (seconds between each refresh)
# These control how often Celery Beat triggers each refresh task
# Default 1 minute (60s)
METADATA_REFRESH_WIKIDATA_INTERVAL = int(
    os.getenv("METADATA_REFRESH_WIKIDATA_INTERVAL", "60")
)
METADATA_REFRESH_OSM_INTERVAL = int(os.getenv("METADATA_REFRESH_OSM_INTERVAL", "60"))

# Default queue for tasks not explicitly routed
CELERY_TASK_DEFAULT_QUEUE = "urgent"
CELERY_TASK_DEFAULT_EXCHANGE = "tasks"
CELERY_TASK_DEFAULT_EXCHANGE_TYPE = "direct"
CELERY_TASK_DEFAULT_ROUTING_KEY = "urgent"

# Queue definitions
CELERY_TASK_QUEUES = {
    "urgent": {
        "exchange": "tasks",
        "routing_key": "urgent",
    },
    "background": {
        "exchange": "tasks",
        "routing_key": "background",
    },
}

# Celery Beat schedule for periodic tasks
# Rate limiting is achieved by Beat's schedule interval, not per-worker limits
CELERY_BEAT_SCHEDULE = {
    "refresh-next-wikidata-item": {
        "task": "subjects.tasks.refresh_next_wikidata_item",
        "schedule": float(METADATA_REFRESH_WIKIDATA_INTERVAL),
    },
    "refresh-next-osm-element": {
        "task": "subjects.tasks.refresh_next_osm_element",
        "schedule": float(METADATA_REFRESH_OSM_INTERVAL),
    },
}

# External Metadata Refresh Settings
# Hours after which metadata is considered stale and needs refresh
METADATA_REFRESH_STALE_HOURS = int(os.getenv("METADATA_REFRESH_STALE_HOURS", "24"))
# Max consecutive failures before giving up on a record
METADATA_REFRESH_MAX_FAILURES = int(os.getenv("METADATA_REFRESH_MAX_FAILURES", "5"))
# Postpass API settings for OSM geometry fetching
METADATA_REFRESH_POSTPASS_URL = os.getenv(
    "METADATA_REFRESH_POSTPASS_URL",
    "https://postpass.geofabrik.de/api/0.2/interpreter",
)
METADATA_REFRESH_POSTPASS_TIMEOUT = int(
    os.getenv("METADATA_REFRESH_POSTPASS_TIMEOUT", "60")
)
# Bounding box for OSM queries (Virginia and surrounding area)
METADATA_REFRESH_POSTPASS_BBOX = os.getenv(
    "METADATA_REFRESH_POSTPASS_BBOX",
    "ST_SetSRID(ST_MakeBox2D(ST_MakePoint(-84.72, 35.90), ST_MakePoint(-74.97, 39.71)), 4326)",
)

# OSM Authentication Settings
OSM_URL = os.getenv("OSM_URL", "https://www.openstreetmap.org")
OSM_CLIENT_ID = os.getenv("OSM_CLIENT_ID")
OSM_CLIENT_SECRET = os.getenv("OSM_CLIENT_SECRET")
OSM_SECRET_KEY = os.getenv("OSM_SECRET_KEY")
OSM_LOGIN_REDIRECT_URI = os.getenv("OSM_LOGIN_REDIRECT_URI")
OSM_SCOPE = "read_prefs"

# OSM Admin Settings
OSM_ADMIN_USERNAMES = (
    os.getenv("OSM_ADMIN_USERNAMES", "").split(",")
    if os.getenv("OSM_ADMIN_USERNAMES")
    else []
)

# Authentication Backends
AUTHENTICATION_BACKENDS = [
    "osm_auth.auth_backends.OSMAuthBackend",  # Primary: OSM OAuth authentication
    "django.contrib.auth.backends.ModelBackend",  # Usually unused
]

# Optional hardcoded admin (enabled by default in LOCAL_DEV mode unless explicitly overwritten)
if LOCAL_DEV and os.getenv("ALLOW_HARDCODED_ADMIN") is None:
    ALLOW_HARDCODED_ADMIN = True
else:
    ALLOW_HARDCODED_ADMIN = DEBUG and os.getenv(
        "ALLOW_HARDCODED_ADMIN", "false"
    ).lower() in ("true", "1", "yes")

if ALLOW_HARDCODED_ADMIN:
    AUTHENTICATION_BACKENDS.append("osm_auth.auth_backends.HardcodedAdminBackend")

# Session settings for authentication
SESSION_COOKIE_AGE = 86400  # 24 hours
SESSION_SAVE_EVERY_REQUEST = True

# Login URL for @login_required decorator
LOGIN_URL = "/auth/login/"

# Map Settings
# Protomaps API key for map tiles
PROTOMAPS_API_KEY = os.getenv("PROTOMAPS_API_KEY")

# MapLibre style URL for OSM base map
OSM_STYLE_URL = os.getenv(
    "OSM_STYLE_URL", "https://styles.maprva.org/openmaptiles-osm.json"
)

# Activity Feed Settings
# Milestone thresholds for user georeference achievements
ACTIVITY_MILESTONE_THRESHOLDS = [
    5,
    15,
    50,
    100,
    250,
    500,
    1000,
    2000,
    3000,
    4000,
    5000,
    6000,
    7000,
    8000,
    9000,
    10000,
]
