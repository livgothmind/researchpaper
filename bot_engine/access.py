from django.conf import settings

from .models import UserGroupMembership


def is_email_blacklisted(email, username=""):
    email_norm = (email or "").strip().lower()
    username_norm = (username or "").strip().lower()

    if not email_norm:
        return False

    exempt_emails = getattr(settings, "BLACKLIST_EXEMPT_EMAILS", []) or []
    exempt_usernames = getattr(settings, "BLACKLIST_EXEMPT_USERNAMES", []) or []
    if email_norm in exempt_emails or username_norm in exempt_usernames:
        return False

    patterns = getattr(settings, "BLACKLIST_EMAIL_PATTERNS", []) or []
    return any(p and p in email_norm for p in patterns)


def user_is_blacklisted(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return False
    return is_email_blacklisted(user.email, user.username)


def user_can_interact(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return UserGroupMembership.objects.filter(user=user).exists()
