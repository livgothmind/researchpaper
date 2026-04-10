from django.contrib import admin
from django.urls import path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from bot_engine import views

urlpatterns = [
    path("admin/", admin.site.urls),

    path("login/",  views.login_view,  name="login"),
    path("logout/", views.logout_view, name="logout"),

    path("",           views.upload_poster, name="upload"),
    path("dashboard/", views.dashboard,     name="dashboard"),
    path("conference/",            views.conference_view,   name="conference"),
    path("api/conference-search/", views.conference_search, name="conference_search"),

    path("task-status/<str:task_id>/",    views.task_status,           name="task_status"),
    path("dashboard/live-status/",        views.dashboard_live_status, name="dashboard_live_status"),

    path("edit/<int:poster_id>/",            views.edit_poster,    name="edit_poster"),
    path("poster/<int:poster_id>/",          views.poster_detail,  name="poster_detail"),
    path("update-status/<int:poster_id>/",   views.update_status,  name="update_status"),
    path("delete/<int:poster_id>/",          views.delete_poster,  name="delete_poster"),
    path("toggle-favorite/<int:poster_id>/", views.toggle_favorite, name="toggle_favorite"),
    path("update-notes/<int:poster_id>/",    views.update_notes,   name="update_notes"),
    path("update-tags/<int:poster_id>/",     views.update_tags,    name="update_tags"),
    path("bulk-action/",                     views.bulk_action,    name="bulk_action"),
    path("delete-all-activities/",           views.delete_all_activities, name="delete_all_activities"),

    path("api/tags-autocomplete/", views.tags_autocomplete, name="tags_autocomplete"),

    path("retry-analysis/<int:poster_id>/", views.retry_analysis, name="retry_analysis"),
    path("stop-analysis/<int:poster_id>/",  views.stop_analysis,  name="stop_analysis"),

    path("export/approved/csv/",  views.export_approved_csv,  name="export_approved_csv"),
    path("export/approved/json/", views.export_approved_json, name="export_approved_json"),

    path("telegram-webhook/",  views.telegram_webhook,  name="telegram_webhook"),
    path("whatsapp-webhook/",  views.whatsapp_webhook,  name="whatsapp_webhook"),
]

urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]