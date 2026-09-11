# Стратегия тестирования

Дата: 2026-09-11. Реализованы проверки DOC-01 и BOOT-01 для пустого каркаса PR-01. Остальные тестовые ID и пути ниже — спецификация будущих тестов, а не уже работающий suite. ORM-модели, миграции и доменная логика на этом этапе не создаются.

## Что доказываем

Главные доказательства — инварианты [требований](product/requirements.md): отсутствие пересечений, атомарность, безопасные повторы, допустимый lifecycle, правильный календарь, независимость локального commit от Яндекса. Проверка процентов покрытия не заменяет эти доказательства.

| Уровень | Что проверяет | Окружение |
| --- | --- | --- |
| Unit / property-based | Интервалы, календарь, guards, канонизацию команд, backoff | Без сети; управляемые clock/random; Hypothesis для граничных случаев |
| PostgreSQL integration | Constraints, atomicity, receipts, mapping, migrations | PostgreSQL той же major-версии и расширений, что production |
| Concurrency | Реальное ожидание locks, commit/rollback и конкурентные исходы | Независимые соединения, отдельные транзакции, barriers/events |
| API / security | Права, object scope, CSRF, replay и HTTP/OpenAPI | Настоящие application services и БД |
| Contract | Согласованную схему и поведение адаптера | Обезличенные fixtures закреплённого контракта + управляемый HTTP stub |
| Fault / recovery | Crash, потерю ответа, истёкший lease, PITR | Отдельные процессы и disposable инфраструктура |
| Performance | Задержки, contention, пределы соединений и backlog | Выделенный стенд с зафиксированными ресурсами |

Запретить SQLite fallback в integration/concurrency. `pytest.mark.django_db(transaction=True)` либо TransactionTestCase обязателен там, где проверяется настоящий commit. Каждая конкурентная операция получает собственное соединение; fixture, скрывающая всё внутри одной внешней транзакции, недопустима. Простого `pytest-xdist` или последовательного вызова двух HTTP-запросов недостаточно для доказательства гонки.

Для воспроизводимости использовать barriers перед конфликтующим участком, события для управления commit первой транзакции, ограниченные joins и сохранение seed. Не синхронизировать потоки случайным sleep. Проверять и ответы, и итоговые строки/версии/audit/outbox после завершения всех транзакций. Инвариантный stress-тест имеет достаточный deadline для завершения всех конкурентов; отдельный тест короткого deadline должен ожидать retryable error, а не slot conflict.

## Каталог сценариев

ID обозначает семейство тестов; его можно дополнять на следующих PR, не переименовывая требование. Пути появятся в указанных шагах [roadmap](roadmap.md).

| ID | Автоматическое доказательство | Планируемый основной путь | PR |
| --- | --- | --- | --- |
| DOC-01 | Обязательные документы, локальные ссылки, структура ADR/шагов и ссылки на тестовые ID корректны | Встроенная команда ниже | 00 |
| BOOT-01 | Чистая установка по lockfile, Django check и health без бизнес-сущностей | `tests/smoke/test_bootstrap.py` | 01 |
| MIG-01 | Реальный PostgreSQL, btree_gist, UTC, clean migrate и отсутствие незаписанных миграций | `tests/integration/test_database.py` | 02, далее все миграции |
| AUTH-01 | Мастер/администратор не получают чужой филиал; роли не повышаются через payload; replay заново проверяет scope | `tests/security/test_permissions.py` | 03, 14, 18 |
| CAT-01 | Валидные цена/длительность/допуск; изменение каталога не меняет snapshot существующей записи | `tests/integration/test_catalog.py` | 04, 09 |
| TIME-01 | UTC round-trip, naive rejection, полночь, DST gap/fold, lead time и смена timezone процесса | `tests/unit/test_time.py` | 05, 06, 10 |
| SCH-01 | Исключения имеют приоритет над сменой; сокращение смены не обесценивает будущую запись | `tests/integration/test_schedule.py` | 05, 09 |
| DB-01 | Обход service прямым SQL не позволяет пересечение, пустой/null range и несовместимые ссылки; разные мастера и соседние интервалы допустимы | `tests/integration/test_booking_constraints.py` | 06 |
| AUD-01 | Успешная команда имеет одну версию, аудит и обязательное событие; rollback не оставляет их отдельно | `tests/integration/test_journals.py` | 07, 09 |
| IDEM-01 | Параллельный replay, payload mismatch, scope isolation, отказ после tombstone, исходный ответ после потерянного HTTP | `tests/integration/test_idempotency.py`, `tests/concurrency/test_replays.py` | 08, 09, 14 |
| TX-01 | Failpoint до commit откатывает все эффекты; crash после commit сохраняет receipt и событие; ошибка commit разрешается повтором | `tests/faults/test_booking_commit.py` | 09 |
| CON-01 | 20 create на один ресурс дают один успех; другая дата/мастер не блокируются глобально; гонка с изменением расписания безопасна | `tests/concurrency/test_create.py` | 09 |
| AVL-01 | Слоты соответствуют расписанию и полному интервалу; выдача не резервирует; диапазон ограничен | `tests/integration/test_availability.py` | 10 |
| LIFE-01 | Отмена и повтор: правила срока, no-op, version, причина и атомарное освобождение; terminal не удалён | `tests/integration/test_cancellation.py` | 11 |
| CON-02 | Cancel/create дают допустимый сериализованный исход, чужая новая бронь не теряется | `tests/concurrency/test_cancel_create.py` | 11 |
| MOVE-01 | Два переноса одной версии, перенос/create, перенос/cancel, конфликт нового времени сохраняют корректное состояние | `tests/integration/test_reschedule.py`, `tests/concurrency/test_reschedule.py` | 12 |
| LIFE-02 | Complete/no-show только после end_at; запрещённые переходы и competing terminal отклоняются | `tests/integration/test_outcomes.py` | 13 |
| API-01 | HTTP-коды, OpenAPI, guest session, capability token, отсутствующий key/version, no-store и replay согласованы | `tests/api/test_booking_api.py` | 14 |
| OUT-01 | Нет события до commit; два worker не теряют delivery; lease recovery и устаревший owner безопасны | `tests/integration/test_outbox.py` | 07, 15 |
| OUT-02 | Crash до/после HTTP ACK, timeout с поздним применением, backoff, parked/replay и восстановление очереди | `tests/faults/test_delivery.py` | 15, 19 |
| YAN-01 | Fixture/schema validation, JWT claims, фильтрация scope, даты и capability flags соответствуют зафиксированному контракту | `tests/contracts/test_yandex_contract.py`, `tests/contracts/test_yandex_reads.py` | 16, 17 |
| YAN-02 | Внешние повторы/stale update/отмена проходят общие инварианты; неизвестный mapping не создаёт Booking | `tests/integration/test_yandex_commands.py` | 18 |
| YAN-03 | Исходящая проекция/статус/повтор соответствуют контракту; старая доставка не остаётся последним состоянием после сверки | `tests/contracts/test_yandex_delivery.py` | 19 |
| REC-01 | Drift, orphan, разрыв watermark, повтор страницы и crash checkpoint приводят к сверке/issue, не к слепому импорту | `tests/integration/test_reconciliation.py` | 20 |
| OBS-01 | Метрики latency/backlog/lease и alerts срабатывают; PII отсутствует в логах/traces/labels | `tests/operations/test_observability.py` | 21 |
| SEC-01 | CSRF, токены, лимиты, redaction, anonymization/retention hold и удаление PII после restore | `tests/security/test_data_lifecycle.py` | 14, 22, 24 |
| OPS-01 | Контейнеры/health, права app/migrator, graceful shutdown, совместимость предыдущего образа с новой схемой | `tests/operations/test_deployment.py` | 23 |
| OPS-02 | Restore/PITR в отдельной среде, измерение RPO/RTO, проверка receipts/outbox, блокировка канала до сверки | `tests/operations/test_recovery.py` | 24 |
| PERF-01 | Нагрузка NFR-02, всплеск одного ресурса и outage канала сохраняют инварианты и укладываются в согласованные бюджеты | `tests/performance/test_booking_load.py` | 25 |
| REL-01 | Preflight отклоняет неподтверждённые launch gates, drift схемы/контракта и незавершённые инциденты | `tests/operations/test_release_readiness.py` | 26 |

Тест SLA/SLO измеряет ограниченный прогон, а не месячную доступность. Mock Яндекса проверяет нашу реализацию предположений; соответствие реальной среде доказывает отдельный sandbox-прогон после согласования. Персональные данные не копируются в fixtures.

## Матрица сбоев

| Точка сбоя | Ожидаемый результат | Семейство |
| --- | --- | --- |
| После Booking до audit/outbox/receipt | Всё откатилось | TX-01 |
| После commit до HTTP-ответа | Повтор получает тот же booking ID; один эффект | IDEM-01, TX-01 |
| Deadlock / lock deadline | Откат и ограниченный retry той же команды; нет ложного «занято» | CON-01 |
| Worker умер после claim | Lease протухает, обработка возобновляется | OUT-01 |
| Яндекс применил запрос, ACK потерян | Неизвестный исход → безопасный retry/readback; без доказанной семантики parked | OUT-02, YAN-03 |
| Старый HTTP применён после новой отмены | Внешнее fencing либо последующая сверка восстанавливает CANCELLED; локальная бронь не открывается | YAN-03, REC-01 |
| БД недоступна | Успешная запись не подтверждается | OPS-01 |
| PITR удалил локальный commit, видимый Яндексу | Канал остановлен, период потерь выделен для разбора; автоматического импорта нет | OPS-02 |

## Команды будущего приложения

Команды запускаются из корня репозитория. Они **ещё не существуют** и станут обязательствами соответствующих PR. Каждый PR добавляет именно используемые им targets, fixtures и тесты; `pytest` с нулём собранных тестов считается ошибкой, а не успешной проверкой. В CI RTK необязателен: выполняется вложенная команда.

| Команда | Когда появляется | Контракт |
| --- | --- | --- |
| `rtk proxy uv sync --frozen` | PR-01 | Установка закреплённых зависимостей, без изменения lockfile |
| `rtk proxy make check` | PR-01 | Ruff check/format check, mypy, Django check, DOC-01; без автоматического исправления |
| `rtk proxy make db-up` | PR-02 | Запуск исключительно локального/CI PostgreSQL и ожидание readiness |
| `rtk proxy make migrate-check` | PR-02 | Clean migrate в disposable БД и проверка `makemigrations --check --dry-run`; без изменения production |
| `rtk proxy uv run pytest <path>` | С PR-01 | Тесты указанной области; test settings выбираются автоматически, production DSN запрещён |
| `rtk proxy make api-schema-check` | PR-14 | Генерация/валидация OpenAPI во временном месте, проверка drift опубликованной схемы |
| `rtk proxy make contract-check` | PR-16 | Проверка snapshot/fixtures без сети и production credentials |
| `rtk proxy make deployment-check` | PR-23 | Сборка/проверка образов и локальный rolling/rollback smoke |
| `rtk proxy make recovery-check` | PR-24 | Disposable restore drill; отказывается от недопустимого target/production DSN |
| `rtk proxy make load-check` | PR-25 | Контролируемая нагрузка исключительно тестового стенда, артефакт с latency/errors/invariants |
| `rtk proxy make release-check` | PR-26 | Read-only preflight доказательств; не публикует и не включает внешний канал |

С PR-02 перед DB-тестами выполнить `rtk proxy make db-up`; изменения схемы дополнительно требуют `rtk proxy make migrate-check`. `make check` обязателен на каждом PR после PR-01. Эти общие команды добавляются к конкретным командам шага roadmap.

PR CI: статические проверки + затронутые unit/integration/API/contract тесты; изменения команд/constraints всегда запускают весь concurrency suite. Проверки основных инвариантов — required checks, не allow-failure. Fault suite выполняется на изменениях транзакций/worker, расширенный stress и recovery — по расписанию и перед релизом; стендовые метрики хранятся артефактом с commit, seed, образом БД и ресурсами.

## DOC-01: проверка текущей документации

Проверка реализована в `scripts/check_docs.py` и запускается командой `rtk proxy uv run --frozen python scripts/check_docs.py` либо как часть `rtk proxy make check`. Она проверяет структуру и трассируемость документов; смысл архитектуры дополнительно требует review. Внешние URL намеренно не запрашиваются при каждом прогоне.

Дополнительно: `rtk git diff --check`. Текущий статус отслеживания проверяется `rtk git status --short`. Успех DOC-01 не означает, что будущие автоматические тесты реализованы или прошли.
