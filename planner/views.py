from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Invite
from .rules import profile_for


@login_required
def dashboard(request):
    profile_for(request.user)
    return render(request, "dashboard.html")


@transaction.atomic
def signup(request, token):
    invite = get_object_or_404(Invite.objects.select_for_update(), token=token, redeemed_at=None)
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if get_user_model().objects.filter(email__iexact=invite.email).exists():
            form.add_error(None, "An account already uses this email.")
        else:
            user = form.save(commit=False)
            user.email = invite.email
            user.save()
            invite.redeemed_at = timezone.now()
            invite.save(update_fields=["redeemed_at"])
            profile_for(user)
            login(request, user)
            return redirect("dashboard")
    return render(request, "auth.html", {"form": form, "heading": "Create account", "email": invite.email})
