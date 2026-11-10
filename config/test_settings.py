import os

os.environ.setdefault("DEBUG", "1")
os.environ.setdefault("SECRET_KEY", "local-test-key-not-for-deployment")

from .settings import *  # noqa: F403

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
