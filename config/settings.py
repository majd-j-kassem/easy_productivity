import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DEBUG = os.getenv("DEBUG") == "1"
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Set SECRET_KEY in the environment or .env.")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework", "planner",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": os.getenv("DATABASE_PATH", BASE_DIR / "db.sqlite3"),
    "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20},
}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en"
TIME_ZONE = "Europe/Budapest"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_BACKEND = ("django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST
                 else "django.core.mail.backends.console.EmailBackend")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "planner@localhost")
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}
