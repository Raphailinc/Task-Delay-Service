![CI](https://github.com/Raphailinc/Task-Delay-Service/actions/workflows/ci.yml/badge.svg)
![Coverage](https://img.shields.io/codecov/c/github/Raphailinc/Task-Delay-Service?label=coverage)

# Task Delay Service

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
# Получить JWT: POST http://localhost:8000/api/token/ {"username": "...", "password": "..."}
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
celery -A Work beat -l info  # планировщик для отправки due-сообщений
```

## Docker Compose
```bash
docker-compose up --build
```
Сервисы: `api` (8000), `worker`, `beat`, `migrate`, `db` (Postgres 16), `redis` (6379). `migrate` и entrypoint применяют миграции перед стартом, `beat` отвечает за периодический опрос due-сообщений. Настройки берутся из `.env` + переменных в `docker-compose.yml`.

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
- Запуск кампании: `POST /api/campaigns/<id>/start/` (опционально `force_resend=true`) -> `202 Accepted`. Повторный старт без `force_resend` для запланированных/запущенных кампаний вернёт `409 Conflict`.
- Планирование отправок происходит в часовом поясе клиента (`Client.timezone`), вычисленный `planned_send_at` хранится в UTC; Celery beat проверяет due-сообщения каждую минуту.
- Аудитория: при указанных `phone_numbers` отправка идёт только на этот список (теги сужают, но не расширяют аудиторию). Пустые `tag` и `phone_numbers` запрещают запуск.
```

## Архитектура
- `Work/` — Django настройки, Celery конфиг, модели/серилиазоры/вьюхи.
- `api/` — DRF эндпоинты, фильтры, Celery задачи.
- `docker-compose.yml` — api + worker + Postgres + Redis; entrypoint применяет миграции.
- `api/tests/` — pytest + pytest-django проверки сериализаторов, фильтрации и задач.

## Переменные окружения
- `DJANGO_SECRET_KEY` — секретный ключ (обязательно в проде).
- `DJANGO_DEBUG` — `True/False`.
- `DJANGO_ALLOWED_HOSTS` — список хостов через запятую (по умолчанию только `localhost,127.0.0.1`).
- `CORS_ALLOWED_ORIGINS` — список разрешённых Origin через запятую; в продакшене CORS по умолчанию закрыт.
- `DATABASE_URL` — строка подключения к БД (по умолчанию SQLite).
- `DJANGO_TIME_ZONE` — часовой пояс (по умолчанию UTC).
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` — брокер и backend задач (по умолчанию Redis `redis://localhost:6379/0`).
- `ACCESS_TOKEN_LIFETIME` / `REFRESH_TOKEN_LIFETIME` задаются через SimpleJWT (см. Work/settings.py).

### Production settings
- DRF по умолчанию требует аутентификацию (`IsAuthenticated`), используйте JWT (`/api/token/`, `/api/token/refresh/`).
- Укажите `DJANGO_ALLOWED_HOSTS` и `CORS_ALLOWED_ORIGINS` для боевого домена, не используйте `CORS_ALLOW_ALL_ORIGINS` в проде.
- Настройте секреты (`DJANGO_SECRET_KEY`, пароли БД/Redis) через env, не храните значения по умолчанию.
- Celery beat должен быть запущен вместе с worker: `celery -A Work beat -l info`.

## Тесты
```bash
pytest
```

## Quality
- Линт/формат: `ruff check .`, `black --check .`
- Тесты: `pytest` (SQLite по умолчанию), в CI — Postgres
- CI: GitHub Actions (`ci.yml`) запускает lint + tests.

## Интеграция
Пример вызова API из Python (requests):
```python
import requests

base = "http://localhost:8000/api"
client = {
    "phone_number": "79000000001",
    "mobile_operator_code": "900",
    "tag": "vip",
    "timezone": "UTC",
}
requests.post(f"{base}/clients", json=client, timeout=5).raise_for_status()

campaign = {
    "start_datetime": "2024-01-01T10:00:00Z",
    "end_datetime": "2024-01-01T12:00:00Z",
    "text_message": "Hello!",
}
resp = requests.post(f"{base}/newsletters", json=campaign, timeout=5)
print(resp.json())
```

## Полезно знать
- `.gitignore` исключает виртуалки, логи и артефакты сборки.
- Старый `celery_config.py` проксирует к `Work.celery` для совместимости, используйте `celery -A Work worker`.
