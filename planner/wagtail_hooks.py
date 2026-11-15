from wagtail.snippets.models import register_snippet

from .models import HelpArticle, OnboardingTemplate

register_snippet(HelpArticle)
register_snippet(OnboardingTemplate)
