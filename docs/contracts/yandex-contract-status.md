# Контракт Яндекс Booking: состояние gate

Дата проверки: 2026-09-16. Область: публичная спецификация для сегмента красоты.

Зафиксирован нормализованный снимок официальной спецификации
[`yandex-booking-v1.public.json`](yandex-booking-v1.public.json), его hash и обезличенные
контрактные fixtures. Это воспроизводимый результат исследования, а не выданный партнёру
raw OpenAPI или доказательство доступа к sandbox.

## Решения YG-01–YG-06

| Gate | Состояние | Решение PR-16 |
| --- | --- | --- |
| YG-01 | blocked_owner_approval | Нет письменного согласования, `partnerName`, sandbox и credentials; канал выключен |
| YG-02 | partial_public_evidence | Направления, HTTP/JWT и основные wire-поля закреплены; rotation/replay и партнёрский raw contract не подтверждены |
| YG-03 | blocked_partner_sandbox | Публичный create не содержит operation ID; `prebookingId` не считается универсальным ключом |
| YG-04 | blocked_partner_sandbox | Публичные update/cancel не содержат версии или условного изменения |
| YG-05 | blocked_partner_sandbox | URL обязательного PUT известен, но ordering/idempotency/readback и полный wire-контракт не доказаны |
| YG-06 | partial_public_evidence | Offset, ISO 8601, optional prebooking и часть запуска известны; rate limits/shutdown и спорные поля требуют согласования |

Матрица [`yandex-capabilities.json`](yandex-capabilities.json) оставляет все возможности
выключенными. `contract-check` запрещает включить capability, пока каждый требуемый gate не
имеет состояние `closed` и локальный evidence-файл.

## Следующее внешнее действие

Владелец подаёт заявку по [официальной инструкции](https://yandex.ru/support/business-priority/ru/manage/booking-api-partners).
После согласования в репозиторий добавляются только обезличенные доказательства: выданная
версия контракта, результаты sandbox-сценариев lost response/stale update и согласованные
правила webhook. `partnerName`, JWT secrets, контакты и переписка в git не помещаются.

