"""
tesi_project/celery.py
Configurazione dell'app Celery.
Importato automaticamente da tesi_project/__init__.py
"""

import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tesi_project.settings")

app = Celery("tesi_project")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()