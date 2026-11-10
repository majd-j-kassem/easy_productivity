from django.conf import settings
from django.db import models


class ProfessionalProfile(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    skills = models.CharField(max_length=500, blank=True, help_text="Separate skills with commas.")
    website = models.URLField(blank=True)
    github = models.URLField(blank=True)
    linkedin = models.URLField(blank=True)
