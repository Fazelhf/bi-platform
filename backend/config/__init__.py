# Expose the Celery app when Celery is installed. In minimal local dev
# (SQLite, no broker) Celery may be absent — that must not break Django.
try:
    from .celery import app as celery_app

    __all__ = ("celery_app",)
except ModuleNotFoundError:  # pragma: no cover
    __all__ = ()
