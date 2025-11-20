import os, json

def dispatch_task(task_name: str, payload: dict):
    # Placeholder: in production, enqueue with Celery, RQ, or a message broker.
    print(f"[QUEUE] Would enqueue {task_name} with payload={json.dumps(payload)[:200]}")
