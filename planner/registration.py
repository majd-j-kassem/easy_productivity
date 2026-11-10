from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .rules import profile_for


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(max_length=254)

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email.")
        return email


class VerificationToken(PasswordResetTokenGenerator):
    key_salt = "planner.registration.VerificationToken"

    def _make_hash_value(self, user, timestamp):
        return super()._make_hash_value(user, timestamp) + str(user.is_active)


verification_token = VerificationToken()


def register(request):
    form = RegistrationForm(request.POST or None)
    if request.method == "POST":
        try:
            with transaction.atomic():
                if form.is_valid():
                    user = form.save(commit=False)
                    user.email = form.cleaned_data["email"]
                    user.is_active = False
                    user.save()
                    path = reverse("verify_email", args=[user.pk, verification_token.make_token(user)])
                    url = request.build_absolute_uri(path)
                    send_mail("Verify your Productivity Studio account", f"Verify your email at {url}",
                              settings.DEFAULT_FROM_EMAIL, [user.email])
                    return render(request, "account_message.html", {
                        "heading": "Check your email",
                        "message": "Open the verification link to activate your account.",
                    })
        except OSError:
            form.add_error(None, "We could not send the verification email. Please try again.")
    return render(request, "auth.html", {"form": form, "heading": "Create account"})


@transaction.atomic
def verify_email(request, user_id, token):
    user = get_object_or_404(get_user_model().objects.select_for_update(), pk=user_id, is_active=False)
    if not verification_token.check_token(user, token):
        raise Http404("Invalid or expired verification link.")
    if request.method == "POST":
        user.is_active = True
        user.save(update_fields=["is_active"])
        profile_for(user)
        return redirect("login")
    return render(request, "account_message.html", {
        "heading": "Verify email", "message": "Confirm to activate your account.", "confirm": True,
    })
