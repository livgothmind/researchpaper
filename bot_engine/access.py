from .models import UserGroupMembership

GROUP_MANAGER_ROLE = "GestoreGruppi"


def is_group_manager(user):
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name=GROUP_MANAGER_ROLE).exists()


def user_can_interact(user):
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or UserGroupMembership.objects.filter(user=user).exists()
