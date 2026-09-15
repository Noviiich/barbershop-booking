# План реализации небольшими PR

Дата: 2026-09-15. PR-00–PR-12 выполнены; LIFE-01/CON-02/MOVE-01 и проверки предыдущих шагов пройдены на PostgreSQL 17. PR-13–PR-26 — будущие работы; их выполнение требует отдельного запроса на реализацию. Номера обозначают логические шаги, а каждый шаг имеет одну основную цель.

Общие правила: до готовности HTTP/security существующие services проверяются напрямую, endpoints выключены. Каждый PR после PR-01 выполняет `rtk proxy make check`, каждый DB-тест с PR-02 — предварительно `rtk proxy make db-up`, каждое изменение схемы — дополнительно `rtk proxy make migrate-check`. Контракты этих будущих команд определены в [testing-strategy](testing-strategy.md). Отсутствующая команда/пустой suite не засчитывается. Ни одна команда ниже не разрешает deployment или запись в реальные внешние аккаунты.

Точки поставки: локальное ядро — PR-01–14; надёжная фоновая доставка — PR-15; интеграция — PR-16–20 при закрытых Yandex gates; эксплуатационная готовность — PR-21–26. Проверку доступа Яндекса можно начать организационно параллельно ядру, не меняя его архитектуру. Для локального релиза Яндекс может оставаться выключенным; release-check должен различать локальный и интеграционный профиль.

## PR-00 — архитектурная база

Цель: согласованный и проверяемый проект без production-кода.

Изменения: AGENTS.md, требования, четыре документа архитектуры, стратегия тестов, этот roadmap, восемь ADR и реестр.

Acceptance criteria: все обязательные документы существуют, source of truth однозначен, риски Яндекса выделены, каждый шаг имеет критерии и команды; нет моделей, миграций или кода приложения.

Автоматический тест: DOC-01 — структура, ссылки, ADR, шаги и известные ID тестов; архитектурный смысл дополнительно проверяется review.

Команды: выполнить встроенную команду DOC-01 из testing-strategy; `rtk git diff --check`; `rtk git status --short`.

Зависимости: нет.

## PR-01 — воспроизводимый каркас

Цель: запускать пустой Django backend и проверки в чистом окружении.

Изменения: pyproject/uv.lock, настройки без бизнес-моделей, health endpoint, Ruff/mypy/pytest, make check, базовый CI и перенос DOC-01 в проверку CI.

Acceptance criteria: закреплены совместимые версии из ADR-001; установка frozen не меняет lock; health отвечает; секреты обязательны в production settings; импорт не требует внешней сети. Бизнес-endpoints отсутствуют.

Автоматический тест: BOOT-01 — clean install/import/check/health; DOC-01.

Команды: `rtk proxy uv sync --frozen`; `rtk proxy make check`; `rtk proxy uv run pytest tests/smoke/test_bootstrap.py`.

Зависимости: PR-00.

## PR-02 — PostgreSQL и проверка миграций

Цель: сделать настоящую БД обязательной для разработки и CI.

Изменения: Compose только dev/CI, PostgreSQL 17, миграция btree_gist, UTC settings, test DSN safeguards, db-up/migrate-check и DB fixtures.

Acceptance criteria: БД доступна, расширение установлено, clean migration проходит, SQLite/production DSN отклоняются; fixtures позволяют независимые транзакции. Проверена возможность btree_gist у выбранного будущего хостинга либо явно записана остающаяся зависимость.

Автоматический тест: MIG-01 — версия/extension/timezone и clean migrate.

Команды: `rtk proxy make db-up`; `rtk proxy make migrate-check`; `rtk proxy uv run pytest tests/integration/test_database.py`.

Зависимости: PR-01.

## PR-03 — идентичность сотрудников и граница прав

Цель: определить actor и разрешённые операции до появления команд записи.

Изменения: Django identity/roles, policy interface для scope филиала, session security и deny-by-default. Привязки к реальному каталогу дополняются PR-04; здесь policy тестируется на явных scope fixtures.

Acceptance criteria: роли нельзя повысить входным payload; мастер и администратор ограничены выданным scope; неаутентифицированный actor не управляет данными; session mutations защищены CSRF.

Автоматический тест: AUTH-01 — матрица ролей и негативные проверки policy/session.

Команды: `rtk proxy uv run pytest tests/security/test_permissions.py`; `rtk proxy make migrate-check`.

Зависимости: PR-02.

## PR-04 — каталог филиала и допуски мастера

Цель: хранить условия услуги и идентичность ресурса в PostgreSQL.

Изменения: минимальный каталог Branch/Barber/ServiceOffering/Assignment, связи scope сотрудников, constraints цены/длительности/валюты, внутренние команды обновления с протоколом locks. Пользовательский CRUD UI вне шага.

Acceptance criteria: мастер имеет глобальный ID; неподходящие филиал/услуга/допуск отклоняются; цены точные, длительность положительна; массовое изменение получает Branch → Barber locks по ID.

Автоматический тест: CAT-01 — constraints/допуски/конкурентное обновление каталога; AUTH-01 расширяется реальными филиалами.

Команды: `rtk proxy uv run pytest tests/integration/test_catalog.py tests/security/test_permissions.py`; `rtk proxy make migrate-check`.

Зависимости: PR-03.

## PR-05 — календарь и изменения расписания

Цель: однозначно получать рабочие интервалы мастера для локальной даты.

Изменения: регулярные смены и исключения, преобразование IANA ↔ UTC, clock interface, политика горизонта/lead time, protocol locks для редактора расписания. Проверка против существующих Booking подключается PR-09; до неё редактор не публикуется.

Acceptance criteria: перерывы/выходные/полночь корректны; gap/fold не выбираются молча; timezone процесса не влияет на результат; каждая мутация расписания берёт lock мастера.

Автоматический тест: TIME-01, SCH-01 — календарные границы и порядок блокировок без ещё не созданных визитов.

Команды: `rtk proxy uv run pytest tests/unit/test_time.py tests/integration/test_schedule.py`; `rtk proxy make migrate-check`.

Зависимости: PR-04.

## PR-06 — физическая защита интервалов

Цель: обеспечить INV-01 на уровне PostgreSQL до публикации create.

Изменения: минимальная persistence-схема Booking со снимками, статусами/версией, согласованным занятым range, ссылками и exclusion constraint. Командный API ещё отсутствует.

Acceptance criteria: пересечение интервалов одного глобального мастера запрещено даже между филиалами; соседние интервалы и разные мастера разрешены; CANCELLED не блокирует, COMPLETED/NO_SHOW сохраняют ограничение; пустые/null/несогласованные интервалы невозможны.

Автоматический тест: DB-01 — прямые независимые SQL INSERT/UPDATE/commit; TIME-01 для round-trip снимков.

Команды: `rtk proxy uv run pytest tests/integration/test_booking_constraints.py tests/unit/test_time.py`; `rtk proxy make migrate-check`.

Зависимости: PR-05.

## PR-07 — аудит и transactional outbox

Цель: подготовить атомарную запись обязательных побочных эффектов.

Изменения: audit/outbox persistence, schema version событий, уникальность booking/version/event kind, минимальные payload. Delivery worker пока отсутствует.

Acceptance criteria: rollback тестовой транзакции убирает booking и события; commit сохраняет согласованные ссылки/версию; audit и событие не содержат raw request/контакт; повторное добавление того же события запрещено.

Автоматический тест: AUD-01 и начальная часть OUT-01 — атомарность append и уникальность.

Команды: `rtk proxy uv run pytest tests/integration/test_journals.py tests/integration/test_outbox.py`; `rtk proxy make migrate-check`.

Зависимости: PR-06.

## PR-08 — durable receipt команды

Цель: безопасно различать повтор, новое намерение и конфликт ключа.

Изменения: CommandReceipt с server-derived scope, fingerprint/version, UNIQUE, результатом и tombstone; общий transactional helper. Пока проверяется на минимальном тестовом эффекте, не дублирует будущую бизнес-логику.

Acceptance criteria: одинаковый ключ/команда дают один эффект; иной payload — conflict; другой scope не читает ответ; transient rollback допускает повтор; tombstone запрещает новое выполнение; expired receipt не выдаётся за актуальную запись.

Автоматический тест: IDEM-01 — параллельные транзакции, crash/rollback, mismatch, retention и scope.

Команды: `rtk proxy uv run pytest tests/integration/test_idempotency.py tests/concurrency/test_replays.py`; `rtk proxy make migrate-check`.

Зависимости: PR-07.

## PR-09 — транзакционное создание записи

Цель: собрать один надёжный CreateBooking service для всех будущих каналов.

Изменения: создание через receipt → resource lock → проверки → booking/audit/outbox → commit; обработка exclusion/savepoint/deadline; запрет конфликтующего изменения расписания. HTTP endpoint ещё не публикуется.

Acceptance criteria: конкурентные create дают один успех; rollback не оставляет частичных эффектов; lost response возвращает прежний ID; расписание нельзя сократить поверх принятой записи; каталог не меняет снимки существующего визита.

Автоматический тест: CON-01, TX-01, AUD-01, IDEM-01; дополнения CAT-01/SCH-01 на реальных Booking.

Команды: `rtk proxy uv run pytest tests/concurrency/test_create.py tests/concurrency/test_replays.py tests/faults/test_booking_commit.py tests/integration/test_catalog.py tests/integration/test_schedule.py tests/integration/test_journals.py`.

Зависимости: PR-08.

## PR-10 — доступность слотов

Цель: выдавать ограниченный список кандидатов из primary БД.

Изменения: read service каталога/слотов, сетка старта, фильтры мастера/услуги, границы диапазона; исключение занятых интервалов.

Acceptance criteria: весь занятый интервал кандидата помещается в смену; даты считаются по филиалу; GET не создаёт reserve/Booking; устаревший показанный слот безопасно отклоняется CreateBooking.

Автоматический тест: AVL-01, TIME-01; свойство: каждый опубликованный слот принимается CreateBooking при неизменной БД и clock, каждый запрещённый интервал исключён.

Команды: `rtk proxy uv run pytest tests/integration/test_availability.py tests/unit/test_time.py`.

Зависимости: PR-09.

## PR-11 — отмена

Цель: освобождать время атомарно с сохранением истории.

Изменения: CancelBooking service, guards/expected_version, причина/override, no-op для уже отменённого состояния, audit/outbox.

Acceptance criteria: доступ/срок проверяются; ровно одна отмена меняет версию; слот свободен после commit; ошибка внешнего канала не участвует в решении; cancel/create не уничтожает новую запись.

Автоматический тест: LIFE-01, CON-02.

Команды: `rtk proxy uv run pytest tests/integration/test_cancellation.py tests/concurrency/test_cancel_create.py`.

Зависимости: PR-09.

## PR-12 — перенос времени

Цель: менять время визита без риска потерять исходное место.

Изменения: RescheduleBooking того же мастера/услуги/филиала, проверка версии и нового интервала, atomic update с аудитом.

Acceptance criteria: конфликт оставляет старое время/версию; два переноса одной версии не проходят одновременно; stale update не отменяет более новое намерение; совпадающее время с актуальной версией — no-op.

Автоматический тест: MOVE-01 — перенос/create, перенос/cancel, два переноса и rollback.

Команды: `rtk proxy uv run pytest tests/integration/test_reschedule.py tests/concurrency/test_reschedule.py`.

Зависимости: PR-10, PR-11.

## PR-13 — выполненный визит и неявка

Цель: завершить минимальный lifecycle без скрытых переходов по часам.

Изменения: CompleteBooking/MarkNoShow, единая таблица guards, no-op повторов, проверка прав мастера/администратора.

Acceptance criteria: исход отмечается только после end_at; terminal не открывается и не переписывается другим исходом; audit/version корректны; исторический интервал остаётся защищённым.

Автоматический тест: LIFE-02 — параметризованная матрица всех переходов и гонки terminal.

Команды: `rtk proxy uv run pytest tests/integration/test_outcomes.py tests/integration/test_booking_constraints.py`.

Зависимости: PR-11.

## PR-14 — собственный HTTP API и управление записью

Цель: предоставить тонкий транспорт над готовыми командами с объектной авторизацией.

Изменения: DRF routes/serializers/OpenAPI, guest scope и management token, replay encryption, session/CSRF, ограничения запросов, no-store; Django Admin Booking только read/actions через service. Дизайн пользовательского интерфейса вне шага.

Acceptance criteria: HTTP-коды/key/version соответствуют booking-flow; токен управляет одной записью, secret не попадает в URL/логи; чужой scope не получает replay; transport не содержит второго алгоритма бронирования.

Автоматический тест: API-01, AUTH-01, IDEM-01 и SEC-01 для токенов/CSRF/rate limit. Если transport и token security не помещаются в малый PR, разделить шаг на подготовку token backend и подключение routes до публикации API.

Команды: `rtk proxy uv run pytest tests/api/test_booking_api.py tests/security/test_permissions.py tests/security/test_data_lifecycle.py tests/integration/test_idempotency.py`; `rtk proxy make api-schema-check`.

Зависимости: PR-03, PR-10, PR-12, PR-13.

## PR-15 — generic worker доставки

Цель: доставлять durable события тестовому получателю при повторах и падениях.

Изменения: DeliveryState/lease/owner token, claim SKIP LOCKED, process lifecycle, bounded backoff/parked/replay, serialization по connection/booking, fake transport. Контракт Яндекса не реализуется здесь.

Acceptance criteria: HTTP вне DB transaction; два worker не теряют задания; crash после внешнего ACK допускает повтор, старый owner не подтверждает новую lease; terminal событие не исчезает при coalescing.

Автоматический тест: OUT-01, OUT-02 с реальными процессами и управляемым получателем.

Команды: `rtk proxy uv run pytest tests/integration/test_outbox.py tests/faults/test_delivery.py`; `rtk proxy make migrate-check`.

Зависимости: PR-07, PR-09.

## PR-16 — проверенный контракт Яндекса

Цель: заменить допущения проверенным артефактом до реализации адаптера.

Изменения: snapshot спецификации с датой/hash, обезличенные fixtures, capability matrix, решения YG-01–YG-06 и contract-check. Новые секреты/договоры в git не помещаются. Если доступа нет, записывается блокировка соответствующего этапа; фиктивные fixtures не закрывают gate.

Acceptance criteria: определены реальные wire статусы/ошибки/auth/идентичность/порядок; неизвестные возможности явно disabled. YG-01 подтверждает владелец, YG-03/04 — проверяемые сценарии повторов и stale update. PR может зафиксировать исследование, но write-подэтапы не продолжаются без необходимых доказательств.

Автоматический тест: YAN-01 — валидность snapshot/fixtures и отказ включить capability без доказательства. Автотест не заменяет партнёрское согласование.

Команды: `rtk proxy make contract-check`; `rtk proxy uv run pytest tests/contracts/test_yandex_contract.py`.

Зависимости: PR-01, PR-00; внешний доступ и согласование для закрытия launch gates.

## PR-17 — чтение через адаптер Яндекса

Цель: отдавать каталог и доступность по согласованному wire-контракту.

Изменения: auth adapter, mapping организаций/услуг/мастеров, read routes и pagination, timezone/error mapping. Неподдерживаемые возможности объявляются ровно по контракту.

Acceptance criteria: подпись/claims и scope проверяются; данные исходят из primary; даты и длительности соответствуют snapshot; timeout укладывается в контрактный бюджет; неизвестные mapping не открывают чужой филиал.

Автоматический тест: YAN-01 — реальные read services + contract fixtures, негативные JWT/scope/dates.

Команды: `rtk proxy make contract-check`; `rtk proxy uv run pytest tests/contracts/test_yandex_reads.py`; `rtk proxy make migrate-check`.

Зависимости: PR-10, PR-16.

## PR-18 — команды канала Яндекса

Цель: подключить внешний канал к уже проверенным транзакционным командам.

Изменения: внешние create/update/cancel routes, InboxReceipt/CommandReceipt mapping, operation identity и причинность из контракта; общий service без обходных ORM writes.

Acceptance criteria: YG-03/04 закрыты; дубликаты/потерянный ответ возвращают один ID; запоздавший перенос не откатывает новую версию; DELETE отменяет, не удаляет; неизвестный статус/ID не импортируется. Ограничения одной услуги проверяются контрактом.

Автоматический тест: YAN-02, AUTH-01; гонка OWN_WEB/STAFF/YANDEX на один интервал через независимые HTTP-клиенты.

Команды: `rtk proxy uv run pytest tests/integration/test_yandex_commands.py tests/security/test_permissions.py tests/concurrency`; `rtk proxy make contract-check`.

Зависимости: PR-08, PR-14, PR-17; YG-03 и YG-04.

## PR-19 — исходящие обновления Яндекса

Цель: передавать локальные изменения и исход визита через generic worker.

Изменения: HTTPX transport/проекции статусов, проверенная retry-семантика, auth rotation hooks, causal echo policy, обработка неизвестного результата/readback.

Acceptance criteria: YG-05 закрыт; локальная отмена проходит при outage; потерянный ACK и поздний HTTP не повреждают локальную запись; неподтверждённая повторяемость приводит к parked/issue, не слепому повтору; version/desired cursor корректны.

Автоматический тест: YAN-03, OUT-02 — deadline, retry, позднее применение, coalescing и echo.

Команды: `rtk proxy uv run pytest tests/contracts/test_yandex_delivery.py tests/faults/test_delivery.py`; `rtk proxy make contract-check`.

Зависимости: PR-15, PR-18; YG-05.

## PR-20 — сверка и разбор расхождений

Цель: обнаруживать и устранять внешнее отставание из локального source of truth.

Изменения: reconciliation job, checkpoint/watermark, issue storage, dry-run/report/replay для оператора; явно ограниченный режим без внешнего readback.

Acceptance criteria: crash/повтор страницы не теряет остаток; orphan не создаёт Booking; desired состояние сходится после восстановления канала; отчёт отличает подтверждённое расхождение от отсутствия read-возможности; действия оператора аудируются.

Автоматический тест: REC-01 — drift/orphan/pagination/crash и неизвестный исход доставки.

Команды: `rtk proxy uv run pytest tests/integration/test_reconciliation.py tests/contracts/test_yandex_delivery.py`; `rtk proxy make migrate-check`.

Зависимости: PR-19.

## PR-21 — наблюдаемость

Цель: измерять работу локальных команд и backlog без раскрытия данных клиентов.

Изменения: JSON logs, trace correlation, latency/conflict/lock/retry/lease/backlog метрики, alert rules и краткий runbook. Нет автоматических сообщений клиентам.

Acceptance criteria: просроченный backlog >5 мин и auth failure дают alert; booking ID/контакты не используются как metric labels; ошибки имеют correlation ID; outage Яндекса отличим от отказа primary.

Автоматический тест: OBS-01 — metrics/alert fixtures и redaction логов/traces.

Команды: `rtk proxy uv run pytest tests/operations/test_observability.py`.

Зависимости: PR-14, PR-15; PR-20 нужен только для метрик включённого канала.

## PR-22 — жизненный цикл персональных данных

Цель: обеспечить управляемое хранение и обезличивание без поломки dedup/audit.

Изменения: retention jobs, tombstone/hold policy, redaction, token rotation/revocation и запись факта обезличивания для restore; документирование владельца сроков и размещения данных.

Acceptance criteria: контакт удаляется по принятой политике; исторический интервал и receipt identity сохраняют заявленные гарантии; hold обоснован и видим; повтор очистки безопасен; expiry токена не раскрывает replay. Утверждение сроков владельцем требуется перед публичным запуском, а не выдумывается тестом.

Автоматический тест: SEC-01, IDEM-01 — fake clock, границы retention, hold, повтор очистки и replay после удаления контакта.

Команды: `rtk proxy uv run pytest tests/security/test_data_lifecycle.py tests/integration/test_idempotency.py`.

Зависимости: PR-14, PR-21.

## PR-23 — пакет поставки и безопасный откат

Цель: воспроизводимо запускать API/worker и совместимо обновлять схему.

Изменения: production OCI-образ без секретов, deployment template, readiness/liveness, migrator/app роли, graceful shutdown, smoke expand/contract и runbook отката. Реальный deploy вне PR.

Acceptance criteria: app не имеет DDL-прав; Яндекс outage не снимает readiness; primary outage запрещает успешный create; предыдущий образ работает с расширенной схемой; остановка процесса не теряет committed outbox.

Автоматический тест: OPS-01, MIG-01 — disposable deployment и rollback smoke.

Команды: `rtk proxy make deployment-check`; `rtk proxy uv run pytest tests/operations/test_deployment.py tests/integration/test_database.py`.

Зависимости: PR-15, PR-21, PR-22.

## PR-24 — проверяемое восстановление

Цель: подтвердить RPO/RTO и безопасное поведение после потери данных.

Изменения: backup/PITR configuration для выбранного хостинга, recovery-check на отдельном disposable target, runbook восстановления ключей/данных/канала и повторного обезличивания.

Acceptance criteria: восстановление измерено и укладывается в принятый бюджет; чужой/production target отклоняется; receipts/outbox восстановлены; канал остаётся на паузе до сверки периода потерь; удалённые контакты не возвращаются в эксплуатацию.

Автоматический тест: OPS-02 и SEC-01 — synthetic подтверждения до/после recovery point, сверка внешнего stub и privacy ledger.

Команды: `rtk proxy make recovery-check`; `rtk proxy uv run pytest tests/operations/test_recovery.py tests/security/test_data_lifecycle.py`.

Зависимости: PR-23; PR-20 для профиля с Яндексом.

## PR-25 — нагрузка и устойчивость при contention

Цель: проверить заявленные бюджеты на воспроизводимом стенде.

Изменения: deterministic load fixture из NFR-02, load-check, отчёт percentile/error/locks/backlog и ограничений стенда. Функциональную переработку по найденным проблемам выносить в отдельные небольшие PR.

Acceptance criteria: 10 минут прогрева + 30 минут steady load по профилю NFR-02, отдельный burst одного ресурса; ни одного нарушения DB-инварианта; p95/p99 измерены; outage внешнего stub не блокирует локальный create; отчёт фиксирует ресурсы API/БД и commit.

Автоматический тест: PERF-01 и повтор обязательного concurrency suite. Если SLO не достигнут, шаг не считается завершённым одной публикацией графика.

Команды: `rtk proxy make load-check`; `rtk proxy uv run pytest tests/concurrency`.

Зависимости: PR-23, PR-24; PR-20 для профиля с Яндексом.

## PR-26 — готовность к пилоту

Цель: собрать проверяемый release candidate и конкретные условия запуска.

Изменения: release-check, реестр доказательств/владельцев gates, staging smoke-сценарий, план ограничения пилота одним филиалом и runbook выключения канала. Запуск production не входит в команду проверки.

Acceptance criteria: локальный профиль закрывает продуктовые/retention/операционные gate и required tests; профиль Яндекса дополнительно закрывает YG-01–YG-06, sandbox create/replay/reschedule/cancel/sync и согласованный способ отключения. Состояние «mock проходит, доступ отсутствует» не является готовностью интеграции. Блокировка Яндекса не мешает локальному профилю при выключенном канале.

Автоматический тест: REL-01 — preflight отклоняет недостающие доказательства/просроченный контракт/открытые критичные issues; автоматизированный staging smoke выполняется только с тестовыми данными. Продуктовые согласования и реальный доступ проверяются ответственными людьми.

Команды: `rtk proxy make release-check`; `rtk proxy uv run pytest tests/operations/test_release_readiness.py`; для интеграционного профиля также `rtk proxy make contract-check`.

Зависимости: PR-25; PR-20 и закрытые YG-01–YG-06 для профиля Яндекса.
