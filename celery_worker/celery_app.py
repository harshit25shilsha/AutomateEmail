# celery_worker/celery_app.py
from celery import Celery
from dotenv import load_dotenv
import os

load_dotenv()

celery_app = Celery(
    "email_monitor",
    broker  = os.getenv("REDIS_URL"),
    backend = os.getenv("REDIS_URL"),
    include = ["celery_worker.tasks"]
)

celery_app.conf.update(
    task_serializer            = "json",
    result_serializer          = "json",
    accept_content             = ["json"],
    timezone                   = "UTC",
    task_acks_late             = True,
    task_reject_on_worker_lost = True,
    worker_pool = "gevent"
)