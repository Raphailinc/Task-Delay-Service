# Task Delay Service

[![CI](https://github.com/Raphailinc/Task-Delay-Service/actions/workflows/ci.yml/badge.svg)](https://github.com/Raphailinc/Task-Delay-Service/actions/workflows/ci.yml)

[English](README.md) · [Русский](README.ru.md)

A backend portfolio service for preparing and scheduling message campaigns. It models recipients, campaign runs and per-recipient delivery state.

## What it does

- Validate campaign dates, daily sending windows and recipient criteria.
- Calculate planned sending times in each recipient's time zone and store them in UTC.
- Use explicit campaign/run/message states and reject repeated starts unless a resend is requested.
- Run the API, migrations, Celery worker and beat alongside PostgreSQL and Redis in Compose.

## Run locally

```bash
cp .env.example .env
# Configure DJANGO_SECRET_KEY and local database credentials.
docker compose up --build
```

## Checks

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
ruff check .
black --check .
```

## Scope and implementation notes

API: `http://localhost:8000/api/`. Obtain JWT credentials from `/api/token/` using an existing Django user; create one with `docker compose exec api python manage.py createsuperuser`. The local test suite uses SQLite unless `DATABASE_URL` is set; the existing CI also exercises PostgreSQL. Worker and beat must both run for scheduled processing.

## API example

Requests require a bearer token. The route is `/api/campaigns/`.

```http
POST /api/campaigns/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "start_datetime": "2030-01-01T10:00:00Z",
  "end_datetime": "2030-01-01T18:00:00Z",
  "time_interval_start": "10:00:00",
  "time_interval_end": "18:00:00",
  "text_message": "Hello",
  "tag": "vip",
  "client_filter": {"tags": ["vip"]}
}
```

Start the campaign with `POST /api/campaigns/<id>/start/`; inspect its statistics at `GET /api/campaigns/<id>/stats/`. Client records are managed under `/api/clients/`. See [`api/urls.py`](api/urls.py) for the route list and [`api/serializers.py`](api/serializers.py) for validation rules.

## Reliability checks

Uses Python 3.11+ and Django 5.2 LTS. Regression tests cover daily windows crossing midnight, malformed recipient filters, invalid timezone names and broker publication failures. A failed broker publish returns the message to `PENDING` for a later dispatcher pass.

The provider adapter in `api/services.py` simulates delivery. A real integration must define provider-side idempotency, request timeouts and delivery reconciliation; the demo does not promise exactly-once external delivery.
