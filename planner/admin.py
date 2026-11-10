from django.contrib import admin

from .models import Invite


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("email", "registration_path", "redeemed_at")
    readonly_fields = ("registration_path", "redeemed_at")

    @admin.display(description="Registration link path")
    def registration_path(self, invite):
        return f"/signup/{invite.token}/" if invite.pk else "Save to create the link"
