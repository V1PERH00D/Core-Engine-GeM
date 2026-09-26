from celery import Celery

celery_app = Celery(
    "gem_verification",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)