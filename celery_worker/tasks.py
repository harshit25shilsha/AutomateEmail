# celery_worker/tasks.py
from celery_worker.celery_app import celery_app
from database.db import SessionLocal
from models.hr_user import HRUser
from datetime import datetime, timezone
import services.gmail_service   as gmail_svc
import services.outlook_service as outlook_svc
import redis, json, os

redis_client  = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
POLL_INTERVAL = 600   # 10 minutes


def _get_last_run(hr_id: int, provider: str):
    data = redis_client.get(f"last_run:{provider}:{hr_id}")
    return json.loads(data)["last_run"] if data else None

def _save_last_run(hr_id: int, provider: str):
    redis_client.set(
        f"last_run:{provider}:{hr_id}",
        json.dumps({"last_run": datetime.now(timezone.utc).isoformat()})
    )


# ── Gmail Monitor 
@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="monitor_gmail"
)
def monitor_gmail(self, hr_id: int):
    # Stop if monitor was stopped
    if not redis_client.get(f"monitor:gmail:{hr_id}"):
        return

    db = SessionLocal()
    try:
        hr_user  = db.query(HRUser).filter_by(id=hr_id).first()
        if not hr_user:
            return

        last_run  = _get_last_run(hr_id, "gmail")
        after     = datetime.fromisoformat(last_run).strftime(
            '%Y/%m/%d'
        ) if last_run else None

        new_count = gmail_svc.fetch_and_store_emails(
            hr_user, db, after_date=after
        )
        _save_last_run(hr_id, "gmail")
        print(f"[Gmail][HR {hr_id}] {new_count} new emails at "
              f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    except Exception as e:
        print(f"[Gmail][HR {hr_id}] Error: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()

    # Schedule next run
    monitor_gmail.apply_async(args=[hr_id], countdown=POLL_INTERVAL)


# ── Outlook Monitor 
@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="monitor_outlook"
)
def monitor_outlook(self, hr_id: int):
    if not redis_client.get(f"monitor:outlook:{hr_id}"):
        return

    db = SessionLocal()
    try:
        hr_user  = db.query(HRUser).filter_by(id=hr_id).first()
        if not hr_user:
            return

        last_run  = _get_last_run(hr_id, "outlook")
        new_count = outlook_svc.fetch_and_store_emails(
            hr_user, db, after_date=last_run
        )
        _save_last_run(hr_id, "outlook")
        print(f"[Outlook][HR {hr_id}] {new_count} new emails at "
              f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    except Exception as e:
        print(f"[Outlook][HR {hr_id}] Error: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()

    monitor_outlook.apply_async(args=[hr_id], countdown=POLL_INTERVAL)