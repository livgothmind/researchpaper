# tesi_project/__init__.py
# Carica l'app Celery quando Django si avvia
from .celery import app as celery_app

__all__ = ("celery_app",)