from django.contrib import admin
from .models import ResearchPoster, ActivityLog, Favorite


@admin.register(ResearchPoster)
class ResearchPosterAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'authors',
        'category',
        'validation_status',
        'created_at',
        'updated_at',
    )
    list_filter = (
        'validation_status',
        'category',
        'created_at',
        'updated_at',
    )
    search_fields = (
        'title',
        'authors',
        'summary',
        'tags',
        'subfields',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'poster',
        'created_at',
    )
    list_filter = (
        'user',
        'created_at',
    )
    search_fields = (
        'user__username',
        'poster__title',
    )
    readonly_fields = (
        'created_at',
    )


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'action',
        'poster_title',
        'timestamp',
    )
    list_filter = (
        'action',
        'timestamp',
        'user',
    )
    search_fields = (
        'poster_title',
        'details',
        'user__username',
    )
    readonly_fields = (
        'timestamp',
    )