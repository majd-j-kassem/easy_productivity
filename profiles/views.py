from django import forms
from django.contrib.auth.decorators import login_required
from django.core.validators import URLValidator
from django.shortcuts import redirect, render

from planner.rules import profile_for

from .models import ProfessionalProfile


class ProfileForm(forms.ModelForm):
    bio = forms.CharField(required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 4}))
    website = forms.URLField(required=False, validators=[URLValidator(schemes=["http", "https"])])
    github = forms.URLField(required=False, validators=[URLValidator(schemes=["http", "https"])])
    linkedin = forms.URLField(required=False, validators=[URLValidator(schemes=["http", "https"])])

    class Meta:
        model = ProfessionalProfile
        fields = ("name", "bio", "skills", "website", "github", "linkedin")


@login_required
def edit_profile(request):
    profile, _ = ProfessionalProfile.objects.get_or_create(
        owner=request.user, defaults={"name": profile_for(request.user).name},
    )
    form = ProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("edit_profile")
    return render(request, "profiles/edit.html", {"form": form})
