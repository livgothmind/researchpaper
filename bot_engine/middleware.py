from django.conf import settings
from django.contrib.auth import login, logout, get_user_model
from django.contrib.auth.backends import BaseBackend
from django.shortcuts import render

from .access import is_email_blacklisted, user_is_blacklisted

User = get_user_model()


def _render_access_denied(request):
    response = render(request, "access_denied.html", status=403)
    return response


class ShibbolethBackend(BaseBackend):
    def authenticate(self, request, shib_uid=None, **kwargs):
        if not shib_uid:
            return None
        user, _ = User.objects.get_or_create(username=shib_uid, defaults={"is_active": True})
        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class ShibbolethMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "SHIBBOLETH_AUTH", False):
            return self.get_response(request)

        uid = request.META.get("HTTP_X_SHIB_UID", "").strip()
        shib_email = request.META.get("HTTP_X_SHIB_MAIL", "").strip()

        if uid and is_email_blacklisted(shib_email, uid):
            existing = User.objects.filter(username=uid).first()
    
            if existing and not (existing.is_staff or existing.is_superuser):
                if request.user.is_authenticated and request.user.pk == existing.pk:
                    logout(request)
            return _render_access_denied(request)

        if uid and not request.user.is_authenticated:
            user = User.objects.filter(username=uid).first()
            if not user:
                full_name = request.META.get("HTTP_X_SHIB_CN", "").strip()
                first_name = request.META.get("HTTP_X_SHIB_GIVENNAME", "").strip()
                last_name = request.META.get("HTTP_X_SHIB_SN", "").strip()

                parsed_first = first_name or (full_name.split()[0] if full_name else "")
                parsed_last = last_name or (" ".join(full_name.split()[1:]) if full_name else "")

                user = User.objects.create_user(
                    username=uid,
                    email=shib_email,
                    first_name=parsed_first,
                    last_name=parsed_last,
                )

            login(request, user, backend="bot_engine.middleware.ShibbolethBackend")

        if user_is_blacklisted(request.user):
            logout(request)
            return _render_access_denied(request)

        return self.get_response(request)
