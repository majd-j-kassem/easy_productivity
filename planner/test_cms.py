import pytest

from .models import HelpArticle


@pytest.mark.django_db
def test_wagtail_access_and_published_help(client, django_user_model):
    staff = django_user_model.objects.create_superuser("editor", password="Strong-Password-789!")
    member = django_user_model.objects.create_user("member")
    HelpArticle.objects.create(title="Public help", body="Getting started", published=True)
    HelpArticle.objects.create(title="Hidden draft", body="Draft")
    client.force_login(member)
    assert client.get("/cms/").status_code == 403
    response = client.get("/help/")
    assert b"Public help" in response.content and b"Hidden draft" not in response.content
    client.force_login(staff)
    assert client.get("/cms/").status_code == 200
