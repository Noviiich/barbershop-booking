# ADR-001: основной backend stack

Статус: Accepted. Дата: 2026-09-11.

## Контекст

Нужен транзакционный backend небольшой команды с административными операциями, устойчивой интеграцией и измеримой корректностью. Основная сложность — согласованность записи, а не количество независимых сервисов.

## Решение

Python 3.13, Django 5.2 LTS, DRF 3.16, PostgreSQL 17 с btree_gist, psycopg 3. Синхронный command service в модульном монолите, HTTP через Gunicorn WSGI. Отдельный worker из того же образа, HTTPX для внешних запросов. uv/lockfile, Docker, pytest/pytest-django/Hypothesis, Ruff/mypy. Полный состав — в [overview](../architecture/overview.md).

Точные patch-версии и образы фиксируются при bootstrap; использованы совместимые поддерживаемые ветки, а не floating latest. Совместимость Python и БД подтверждена [Django 5.2 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2/).

## Альтернативы

FastAPI + SQLAlchemy/Alembic подходит технически, но потребует отдельных решений для административного интерфейса и управления правами. NestJS + PostgreSQL уместен для команды TypeScript; такого ограничения сейчас нет. Микросервисы увеличат число границ транзакций без текущей потребности. Django не является условием отсутствия двойной записи: эту гарантию даёт PostgreSQL.

## Последствия

Быстрый путь к поддерживаемому backend и управлению данными; есть зависимость от PostgreSQL и необходимость запрещать обход команд через Django Admin. Асинхронный web stack не вводится без измеренной необходимости. Нужны обновления зависимостей в пределах выбранных веток и план обновления до окончания поддержки.

## Проверка

BOOT-01 и MIG-01; PR-01/02. Команды после bootstrap: `rtk proxy make check`, `rtk proxy make db-up`, `rtk proxy make migrate-check`, `rtk proxy uv run pytest tests/integration/test_database.py`. Критерий: воспроизводимая установка, запуск и миграции на выбранном PostgreSQL. PR-02 реализован, но в текущем окружении MIG-01 ожидает Docker-доступ; production-провайдер БД ещё не выбран, поэтому поддержка `btree_gist` остаётся gate выбора хостинга.
