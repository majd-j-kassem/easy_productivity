from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import ProfessionalProfile, ProfileShare

SHARE_FIELDS = (
    ("name", "Name"), ("bio", "Bio"), ("skills", "Skills"), ("website", "Website"),
    ("github", "GitHub"), ("linkedin", "LinkedIn"),
)
LINK_FIELDS = {"website", "github", "linkedin"}


class ShareForm(forms.Form):
    visible_fields = forms.MultipleChoiceField(choices=SHARE_FIELDS, widget=forms.CheckboxSelectMultiple)


def visible_profile_fields(profile, fields):
    return [
        {"label": label, "value": value, "is_link": key in LINK_FIELDS}
        for key, label in SHARE_FIELDS
        if key in fields and (value := getattr(profile, key))
    ]


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def manage_sharing(request):
    profile = get_object_or_404(ProfessionalProfile, owner=request.user)
    share = ProfileShare.objects.filter(profile=profile).first()
    action = request.POST.get("action")
    if request.method == "POST" and action == "revoke":
        ProfileShare.objects.filter(profile=profile).delete()
        return redirect("manage_sharing")
    form = ShareForm(request.POST or None, initial={"visible_fields": share.visible_fields if share else []})
    preview = None
    if request.method == "POST" and form.is_valid():
        fields = form.cleaned_data["visible_fields"]
        if action == "save":
            ProfileShare.objects.update_or_create(profile=profile, defaults={"visible_fields": fields})
            return redirect("manage_sharing")
        if action == "preview":
            preview = visible_profile_fields(profile, fields)
    url = request.build_absolute_uri(reverse("shared_profile", args=[share.token])) if share else ""
    return render(request, "profiles/share.html", {"form": form, "preview": preview, "url": url})


@never_cache
@require_http_methods(["GET", "HEAD"])
def shared_profile(request, token):
    share = get_object_or_404(ProfileShare.objects.select_related("profile__owner"), token=token,
                              profile__owner__is_active=True)
    response = render(request, "profiles/public.html", {
        "fields": visible_profile_fields(share.profile, share.visible_fields),
        "portfolio": share.profile.published_projects.order_by("id").values_list("snapshot", flat=True),
    })
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response
