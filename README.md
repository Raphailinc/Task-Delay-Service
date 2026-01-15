# Task Delay Service

![CI](https://github.com/Raphailinc/Task-Delay-Service/actions/workflows/ci.yml/badge.svg)

Рассылки на Django + DRF + Celery. Фильтрация клиентов по тегам/кодам оператора/списку телефонов, контроль временных окон, Docker-компоуз с Postgres/Redis и воркером Celery.

## Возможности
- Планирование рассылки по `start_datetime`/`end_datetime` и дневному интервалу времени.
- Фильтр получателей: тег кампании, `mobile_operator_code`, список телефонов в `client_filter`.
- Celery-воркер + Redis (по умолчанию), синхронный режим для тестов через `CELERY_TASK_ALWAYS_EAGER`.
- Docker Compose: api + worker + Postgres + Redis.
- Тесты на pytest/DRF, примеры окружения в `.env.example`.

## Quickstart
```bash
docker compose up --build
# API: http://localhost:8000/api
```

## Локальный запуск
```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env  # и задайте DJANGO_SECRET_KEY
python manage.py migrate
python manage.py runserver
```

Запуск Celery-воркера (локально):
```bash
celery -A Work worker -l info
```

## Docker Compose
```bash
docker-compose up --build
```
Сервисы: `api` (8000), `worker`, `db` (Postgres 16), `redis` (6379). Настройки берутся из `.env` + переменных в `docker-compose.yml`.

## API схемы (пример)
```bash
# создать клиента
POST /api/clients
{
  "phone_number": "79000000001",
  "mobile_operator_code": "900",
  "tag": "vip",
  "timezone": "UTC"
}

# создать рассылку и получить статистику
POST /api/newsletters
{"text_message": "Hello", "start_datetime": "...", "end_datetime": "..."}
GET  /api/newsletters/<id>/stats  -> {"sent_messages": 1, "pending_messages": 0}
```

## Архитектура
- `Work/` — Django настройки, Celery конфиг, модели/серилиазоры/вьюхи.
- `api/` — DRF эндпоинты, фильтры, Celery задачи.
- `docker-compose.yml` — api + worker + Postgres + Redis; entrypoint применяет миграции.
- `api/tests/` — pytest + pytest-django проверки сериализаторов, фильтрации и задач.

## Переменные окружения
- `DJANGO_SECRET_KEY` — секретный ключ (обязательно в проде).
- `DJANGO_DEBUG` — `True/False`.
- `DJANGO_ALLOWED_HOSTS` — список хостов через запятую.
- `DATABASE_URL` — строка подключения к БД (по умолчанию SQLite).
- `DJANGO_TIME_ZONE` — часовой пояс (по умолчанию UTC).
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` — брокер и backend задач (по умолчанию Redis `redis://localhost:6379/0`).

## Тесты
```bash
pytest
```

## Quality
- Линт/формат: `ruff check .`, `black --check .`
- Тесты: `pytest` (SQLite по умолчанию), в CI — Postgres
- CI: GitHub Actions (`ci.yml`) запускает lint + tests.

## Полезно знать
- `.gitignore` исключает виртуалки, логи и артефакты сборки.
- Старый `celery_config.py` проксирует к `Work.celery` для совместимости, используйте `celery -A Work worker`.
