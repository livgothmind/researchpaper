from django.contrib.auth import get_user_model

from .access import user_can_interact


def group_membership_status(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    can_interact = user_can_interact(user)
    if can_interact:
        return {
            "show_no_groups_banner": False,
            "user_can_interact": True,
        }

    User = get_user_model()
    admin_emails = list(
        User.objects
        .filter(is_active=True, is_staff=True)
        .exclude(email="")
        .order_by("username")
        .values_list("email", flat=True)
    )
    return {
        "show_no_groups_banner": True,
        "no_groups_admin_emails": admin_emails,
        "user_can_interact": False,
    }
