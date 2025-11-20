# AI Agency — Fully Automated Starter (Pro)

This is a production-style scaffold to **run your AI marketing agency end-to-end** with APIs, workers, and queues. It’s built to be simple to start and easy to scale.

## What you get
- **FastAPI** service for lead capture, audits, and copy generation.
- **Celery worker** + Redis for background jobs and schedulable tasks.
- **Postgres (optional)** — swap-in later; API uses SQLite by default for zero-config.
- **Docker Compose** for one-command local run.
- **.env** template with all keys.
- **Scripts** to bootstrap and run.

If you uploaded beginner assets, they’re inventoried in `BEGINNER_INVENTORY.txt`. You can move/merge anything into `services/` as needed.

## Quickstart
```bash
git init
cp .env.example .env
# Put your API keys into .env (OPENAI_API_KEY, etc).
./scripts/run_local.sh
```

Open the API docs at: **http://localhost:8080/docs**

## Key Endpoints
- `GET /health` — health check
- `POST /leads` — store a lead `{name,email,brand,niche,website}`
- `GET /leads` — list recent leads
- `POST /campaigns/brief` — queue full campaign generation (async)
- `POST /copy/ad` — generate ad variants (placeholder)
- `POST /copy/email` — generate email (placeholder)
- `POST /audit` — site audit checklist (mocked)

> Replace placeholders in `services/api/llm.py` with real LLM calls.

## Wiring Real Providers
- **OpenAI/Anthropic/Gemini:** add SDK calls in `services/api/llm.py`
- **Email (Resend/SendGrid):** add send logic in a Celery task
- **Payments (Stripe):** add `/webhooks/stripe` + price ids for plans
- **Analytics (PostHog):** emit events on key actions

## Deploy (one-liner pattern)
- **Railway / Fly.io / Render:** build from this repo, set env vars, and run `docker compose` or separate services.
- **Kubernetes:** create Deployments for `api`, `worker`, and a CronJob for `beat`.

## Roadmap
- Add **auth** (Clerk/Auth0) for admin.
- Swap **SQLite → Postgres** for API persistence.
- Add **frontend** (Next.js or Vite) for a client portal.
