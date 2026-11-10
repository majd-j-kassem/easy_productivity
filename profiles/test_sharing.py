import pytest
from django.urls import reverse

from .models import ProfessionalProfile, ProfileShare


@pytest.mark.django_db
def test_shared_profile_exposes_only_selected_fields_and_can_be_revoked(client, django_user_model):
    user = django_user_model.objects.create_user("owner", email="hidden@example.org")
    profile = ProfessionalProfile.objects.create(owner=user, name="Visible name", bio="Hidden bio")
    client.force_login(user)
    url = reverse("manage_sharing")
    assert client.post(url, {"action": "preview", "visible_fields": ["name"]}).status_code == 200
    assert not ProfileShare.objects.exists()
    assert client.post(url, {"action": "save", "visible_fields": ["name"]}).status_code == 302
    share_url = reverse("shared_profile", args=[ProfileShare.objects.get(profile=profile).token])
    client.logout()
    response = client.get(share_url)
    assert response.status_code == 200
    assert b"Visible name" in response.content
    assert b"Hidden bio" not in response.content
    assert b"hidden@example.org" not in response.content
    client.force_login(user)
    client.post(url, {"action": "revoke"})
    assert client.get(share_url).status_code == 404
