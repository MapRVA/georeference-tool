import os

from celery import Celery
from celery.signals import worker_process_init

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "yesterdays.settings")

app = Celery("yesterdays")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Explicitly include tasks from the main project
app.autodiscover_tasks(["yesterdays"])


@worker_process_init.connect
def _warmup_clip_on_worker_init(**_):
    # Fires inside each prefork child after fork. We discard any model
    # state inherited from the parent and force a fresh load: the JIT
    # ScriptModule's C++ thread pools and compile caches don't initialize
    # cleanly across fork, so inference on the inherited object stalls
    # the first time it runs.
    from django.conf import settings

    if not getattr(settings, "CLIP_WARMUP_ENABLED", False):
        return
    import images.tasks

    images.tasks._clip_model = None
    images.tasks._clip_preprocess = None
    images.tasks._clip_device = None
    images.tasks.warmup_clip_model()
