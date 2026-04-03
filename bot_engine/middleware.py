from django.conf import settings
from django.contrib.auth import login, get_user_model
from django.contrib.auth.backends import BaseBackend

User = get_user_model()

class ShibbolethBackend(BaseBackend):
    def authenticate(self, request, shib_uid=None, **kwargs):
        if not shib_uid:
            return None
        user, _ = User.objects.get_or_create(sername=shib_uid,defaults={"is_active": True},)
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
        if uid and not request.user.is_authenticated:
            user = User.objects.filter(username=uid).first()
            if not user:
                email = request.META.get("HTTP_X_SHIB_MAIL", "").strip()
                full_name = request.META.get("HTTP_X_SHIB_CN", "").strip()
                first_name = request.META.get("HTTP_X_SHIB_GIVENNAME", "").strip()
                last_name = request.META.get("HTTP_X_SHIB_SN", "").strip()
            
                parsed_first = first_name or (full_name.split()[0] if full_name else "")
                parsed_last = last_name or (" ".join(full_name.split()[1:]) if full_name else "")
                
                user = User.objects.create_user(
                    username=uid,
                    email=email,
                    first_name=parsed_first,
                    last_name=parsed_last,
                )
            
            login(request, user, backend="bot_engine.middleware.ShibbolethBackend")

        return self.get_response(request)
