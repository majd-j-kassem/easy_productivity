from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import path

from planner import api, registration, reports, views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", auth.LoginView.as_view(template_name="auth.html",
                                          extra_context={"heading": "Sign in"}), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("register/", registration.register, name="register"),
    path("verify-email/<int:user_id>/<str:token>/", registration.verify_email, name="verify_email"),
    path("password-reset/", auth.PasswordResetView.as_view(
        template_name="auth.html", email_template_name="password_reset_email.txt",
        extra_context={"heading": "Reset password"}), name="password_reset"),
    path("password-reset/sent/", auth.PasswordResetDoneView.as_view(
        template_name="account_message.html",
        extra_context={"heading": "Check your email", "message": "If the account exists, a reset link was sent."}),
        name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", auth.PasswordResetConfirmView.as_view(
        template_name="auth.html", extra_context={"heading": "Choose a new password"}), name="password_reset_confirm"),
    path("password-reset/complete/", auth.PasswordResetCompleteView.as_view(
        template_name="account_message.html", extra_context={"heading": "Password updated",
        "message": "You can now sign in with your new password."}), name="password_reset_complete"),
    path("signup/<uuid:token>/", views.signup, name="signup"),
    path("admin/", admin.site.urls),
    path("api/v1/preferences/", api.preferences),
    path("api/v1/reasons/", api.reasons),
    path("api/v1/reasons/<int:pk>/", api.reason_detail),
    path("api/v1/projects/", api.projects),
    path("api/v1/projects/<int:pk>/", api.project_detail),
    path("api/v1/projects/<int:pk>/kinds/", api.kinds),
    path("api/v1/projects/<int:pk>/kinds/<int:kind_id>/", api.kind_detail),
    path("api/v1/projects/<int:pk>/tasks/", api.tasks),
    path("api/v1/projects/<int:pk>/tasks/<int:task_id>/", api.task_detail),
    path("api/v1/projects/<int:pk>/goals/<int:goal_id>/", api.goal_detail),
    path("api/v1/projects/<int:pk>/cycles/", api.draft_cycles),
    path("api/v1/projects/<int:pk>/cycles/<int:cycle_id>/", api.cycle_detail),
    path("api/v1/projects/<int:pk>/cycles/<int:cycle_id>/tasks/", api.tasks),
    path("api/v1/projects/<int:pk>/cycles/<int:cycle_id>/review/", api.review),
    path("api/v1/projects/<int:pk>/plans/<int:plan_id>/", api.plan_detail),
    path("api/v1/projects/<int:pk>/plans/<int:plan_id>/goals/", api.plan_goals),
    path("api/v1/projects/<int:pk>/plans/<int:plan_id>/complete/", api.complete_plan),
    path("api/v1/projects/<int:pk>/targets/<int:target_id>/entries/", api.entry_dates),
    path("api/v1/projects/<int:pk>/targets/<int:target_id>/entries/<str:day>/", api.entry),
    path("api/v1/projects/<int:pk>/finish/", api.finish),
    path("api/v1/projects/<int:pk>/terms/", api.terms),
    path("api/v1/projects/<int:pk>/terms/<int:terms_id>/", api.terms_detail),
    path("api/v1/projects/<int:pk>/ledger/", api.ledger),
    path("api/v1/projects/<int:pk>/ledger/hourly/", api.hourly),
    path("api/v1/projects/<int:pk>/ledger/monthly/", api.monthly),
    path("api/v1/projects/<int:pk>/ledger/<int:receivable_id>/", api.receivable_detail),
    path("api/v1/projects/<int:pk>/ledger/<int:receivable_id>/payments/", api.payments),
    path("api/v1/projects/<int:pk>/ledger/<int:receivable_id>/payments/<int:payment_id>/", api.payment_detail),
    path("api/v1/projects/<int:pk>/report/", reports.report),
    path("api/v1/projects/<int:pk>/report.xlsx", reports.report, {"file_type": "xlsx"}),
    path("api/v1/projects/<int:pk>/report.pdf", reports.report, {"file_type": "pdf"}),
    path("api/v1/notifications/", api.notifications),
    path("api/v1/notifications/<int:pk>/read/", api.notification_read),
]
