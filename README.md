# Task Delay Service

Рассылки на Django + DRF + Celery. Фильтрация клиентов по тегам/кодам оператора/списку телефонов, контроль временных окон, Docker-компоуз с Postgres/Redis и воркером Celery.

## Возможности
- Планирование рассылки по `start_datetime`/`end_datetime` и дневному интервалу времени.
- Фильтр получателей: тег кампании, `mobile_operator_code`, список телефонов в `client_filter`.
- Celery-воркер + Redis (по умолчанию), синхронный режим для тестов через `CELERY_TASK_ALWAYS_EAGER`.
- Docker Compose: api + worker + Postgres + Redis.
- Тесты на pytest/DRF, примеры окружения в `.env.example`.

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

## Полезно знать
- `.gitignore` исключает виртуалки, логи и артефакты сборки.
- Старый `celery_config.py` проксирует к `Work.celery` для совместимости, используйте `celery -A Work worker`.
