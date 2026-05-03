from .access import is_group_manager, user_can_interact


def group_membership_status(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    can_interact = user_can_interact(user)
    return {
        "user_can_interact": can_interact,
        "show_no_groups_banner": not can_interact,
        "is_group_manager": is_group_manager(user),
    }
