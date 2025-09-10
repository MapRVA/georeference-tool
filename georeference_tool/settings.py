"""
Django settings for georeference_tool project.
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

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "osm_auth",
    "images",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "osm_auth.middleware.OSMAuthenticationMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "georeference_tool.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "georeference_tool.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
# Use SQLite for local development, PostgreSQL for production
if LOCAL_DEV:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
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

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

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
