# Task Delay Service

[![CI](https://github.com/Raphailinc/Task-Delay-Service/actions/workflows/ci.yml/badge.svg)](https://github.com/Raphailinc/Task-Delay-Service/actions/workflows/ci.yml)

[English](README.md) · [Русский](README.ru.md)

Backend-проект рассылок на Django/DRF и Celery: аудитория, часовые пояса, запуски кампаний и журнал доставки каждому получателю.

## Возможности

- Валидация дат кампании, дневных интервалов и структуры фильтров аудитории.
- Планирование в часовом поясе получателя с хранением времени в UTC.
- Атомарный захват сообщения воркером, защита от одновременной повторной отправки и учёт повторов Celery.
- Повторная проверка временного окна при задержке задачи в брокере.
- PostgreSQL, Redis, API, worker и beat через Docker Compose.

## Демо без инфраструктуры

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/demo.py
```

Демо получает JWT, создаёт двух синтетических получателей, запускает кампанию через API и выводит статистику. В аудиторию входит один получатель. Celery работает синхронно, провайдер имитирует отправку. Используется временная SQLite-БД, которая удаляется при выходе. Redis, PostgreSQL и внешние аккаунты для демо не нужны; существующая БД не используется.

## API и фоновые процессы через Compose

```bash
cp .env.example .env
# Задайте DJANGO_SECRET_KEY и локальные реквизиты БД.
docker compose up --build
```

API: http://localhost:8000/api/. Создайте пользователя:

```bash
docker compose exec api python manage.py createsuperuser
```

Получите JWT через `POST /api/token/`, затем передавайте `Authorization: Bearer <access_token>`. И worker, и beat должны работать для запланированной обработки.

## Пример API

Создание кампании автоматически планирует её первый запуск:

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

Получатели создаются через `POST /api/clients/` с полями `phone_number`, `mobile_operator_code`, `tag`, `timezone`. Статистика: `GET /api/campaigns/<id>/stats/`. Маршруты — в [api/urls.py](api/urls.py), правила входных данных — в [api/serializers.py](api/serializers.py).

`POST /api/campaigns/<id>/start/` запускает кампанию; повторный запуск уже завершённой кампании требует `{"force_resend": true}`. Параллельный запуск активной или запланированной кампании возвращает `409`, в том числе с `force_resend`.

## Состояния и надёжность

`PENDING → QUEUED → SENDING → SENT`. Условное обновление БД позволяет только одному воркеру перейти в `SENDING`. Транзакция не удерживается во время вызова провайдера. При временной ошибке состояние возвращается в `QUEUED` для максимум трёх повторов после первой попытки; при исчерпании попыток становится `FAILED`. Задержанная задача ждёт следующего допустимого дневного окна, а завершившаяся кампания не отправляется.

[Разбор архитектуры, диаграмма и границы восстановления](docs/delivery-design.md) · [Регрессионные тесты](api/tests/test_delivery_lifecycle.py).

## Проверки

```bash
python -m pytest
ruff check .
black --check .
python manage.py makemigrations --check --dry-run
```

Требуются Python 3.11+ и Django 5.2 LTS. Локальные тесты используют SQLite, если не задан DATABASE_URL. CI запускает PostgreSQL, включая проверку двух одновременных соединений, и полное демо. Проверка конкуренции явно пропускается на SQLite.

Провайдер в `api/services.py` — симулятор. Для реальной доставки нужны ключи идемпотентности провайдера, тайм-ауты и сверка неопределённых результатов. Падение процесса в состоянии `SENDING` требует сверки перед повтором. Гарантия exactly-once для внешних сообщений не заявляется. Аутентифицированные пользователи работают в общем операторском пространстве; изоляции арендаторов здесь нет.
