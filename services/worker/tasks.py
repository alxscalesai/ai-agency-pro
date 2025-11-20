from celery import Celery
import os, json, time, pathlib
from datetime import datetime

REDIS_HOST = os.getenv("REDIS_HOST","redis")
app = Celery("tasks", broker=f"redis://{REDIS_HOST}:6379/0", backend=f"redis://{REDIS_HOST}:6379/1")

@app.task(name="tasks.generate_full_campaign")
def generate_full_campaign(payload: dict):
    # Build campaign (you can enrich this later with real AI calls if you want)
    campaign = {
        "brief": f"Objective: {payload.get('objective')} for {payload.get('brand')} {payload.get('product')}",
        "inputs": payload,
        "assets": {
            "ad_copy": [f"Ad Variant {i+1}" for i in range(5)],
            "emails": [f"Email Flow Step {i+1}" for i in range(3)],
            "hooks": [f"Hook {i+1}" for i in range(5)]
        },
        "checklist": [
            "Install pixels", "Create audiences", "Launch tests", "Measure", "Iterate"
        ]
    }

    # Save inside the container at /app/out (this folder lives in your project due to the volume mount)
    out_dir = pathlib.Path("/app/out")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    fp = out_dir / f"campaign-{ts}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(campaign, f, ensure_ascii=False, indent=2)

    print(f"[CAMPAIGN_SAVED] {fp}")
    return {"file": str(fp), **campaign}
