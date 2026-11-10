import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse


@pytest.mark.django_db
def test_register_verify_and_request_password_reset(client):
    credentials = {"username": "student", "email": "student@example.org",
                   "password1": "Strong-Password-789!", "password2": "Strong-Password-789!"}
    assert client.post(reverse("register"), credentials).status_code == 200
    user = get_user_model().objects.get(username="student")
    assert not user.is_active
    assert not client.login(username="student", password=credentials["password1"])
    link = mail.outbox[0].body.split()[-1]
    assert client.get(link).status_code == 200
    user.refresh_from_db()
    assert not user.is_active
    assert client.post(link).status_code == 302
    assert client.login(username="student", password=credentials["password1"])
    assert client.post(reverse("password_reset"), {"email": user.email}).status_code == 302
    assert len(mail.outbox) == 2
