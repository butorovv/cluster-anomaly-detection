# Решения перед следующим этапом

Продолжение этапа 2: исследовательские решения разрешены новым ТЗ пользователя,
runtime R/B/Y реализован, D1 parity и [D2 исследование](group-detection-real-d2-results.md)
выполнены. Это не утверждение о согласовании руководителем. Старые пункты
контрольной точки ниже описывают предшествующую остановку. Новая распределённая
работа не начиналась; будущие изменения floor/Y bounds/данных требуют явной версии.

Обновление 18.10.2026: выполнена [контрольная точка №1](group-detection-checkpoint-1.md).
10D D1 имеет полный ранг во всех группах, но Y остаётся unknown и выявлены четыре
zero-MAD host scales R. До согласования этапы IV–X не начаты.
Предложения ниже не превращены в принятые решения.

17.10.2026. «Реализовано» ниже относится к локальному B1; «предложено» —
к математическому контракту, который ещё требует согласования.

## Принято в текущей реализации

- Существующий один IF и общая D1-нормализация сохранены. B1 = individual
  Q0.99 по D1 и строгий `score > threshold`; ни отдельного леса на хост,
  ни fallback на глобальный порог. Проверенные старые формулы не меняются.
- Пороговый профиль связан с точными SHA prepared/statistical/IF, F18,
  inventory, D1 и timezone assumption. Использованы прежние проверенные thresholds.
- Nullable local result различает unknown/incomplete/missing от normal.
  Offline-команда не требует DB/Kafka/API; быстрые и реальные тесты раздельны.
- H1/H2/physical profiles, prepared и исторические результаты не перерабатываются.

## Рекомендуемая конфигурация для согласования

| Решение | Основное предложение | Альтернатива / риск |
|---|---|---|
| Group features | 5 host channels; group means + population spreads, d=10 | d=5 means после явного решения по D1; compact vector теряет детали устройств |
| R | temporal host median/MAD; 2 хоста одного канала/знака; per-group D1 Q99 | Spatial median может скрыть minority; правило 2 не доказывает физическую групповую причину |
| B | отдельный group Mahalanobis, ddof1, rcond1e-12, D1 Q99 | При rank<d unknown; не менять существующий узловой D² |
| R/B relation | Различные статистические вопросы, зависимость измеряется | Два голоса могут почти дублироваться; независимость не заявляется |
| Y | Только verified sensor-compatible hard bounds; сейчас unknown | GPU 300 W и PSU 2200 W не готовы как sensor thresholds |
| Y unavailable | require_y_applicability: preliminary R/B, insufficient full decision | degraded_rb допустим только после согласования, с явной неполнотой критериев |
| Time | causal trailing occurrence TTL; основной δ=0, sensitivity 10/30/60 s | TTL продлевает события; unknown прерывает; gap merging=0 |
| IF support | Вариант B: annotation a/n, без обязательного gate | Gate может потерять коллективные субпороговые отклонения |
| Outside | E как локализация; coverage-weighted outside | E≈0 не исключает общий сдвиг |
| Missing data | R/B только при всех 18 полных F18 | Консервативно; будущие partial-composition profiles — отдельная работа |
| Evaluation | D1 fit, D2 research; D3 retrospective, frozen settings | Новый unused day предпочтителен; без labels нет fault F1 |

## Вопросы для согласования

1. Разрешить ли исследовательский degraded R+B при неизвестном Y, или сохранять
   только preliminary signals до получения аппаратных sensor bounds?
2. Принять ли proposed R по минимум двум согласованным узлам вместо единственной
   пространственной медианы группы? Принять ли d=10 mean/spread для B?
3. Какой минимальный D1 coverage/объём считать научно достаточным? Сейчас
   математический минимум N≥d+1 не объявляется статистической достаточностью.
4. Принять ли MAD floor 1e-4 в каждой физической единице, rank-deficient→unknown,
   без автоматической regularization? Как действовать при плохо обусловленном D1?
5. Утвердить ли δ grid, TTL семантику, unknown censoring и отсутствие gap merging?
   Bounded lateness L online-системы потребует отдельного operational требования.
6. Где получить inventory/SKU, BMC SDR/alarms/power caps, job/incident logs,
   физическое соответствие hostname и новый независимый день?

## Что делать дальше

Сначала утвердить спорные пункты и версию спецификации; получить аппаратные
сведения либо явно утвердить degraded policy. Затем отдельным ТЗ реализовать
минимальное offline групповое ядро с контрактными тестами, D1 diagnostics и
протоколом D2. Kafka, Master/Worker, HTTP и GUI не являются prerequisite.
Physical-v1/v2, PostgreSQL, disk guard и FitStatistical optimization остаются
отдельными долгами и в текущем локальном запуске не блокируют B1.

Документы: [математическая спецификация](group-detection-mathematical-spec.md),
[hardware reference](summit-hardware-reference.md),
[протокол](group-detection-evaluation-protocol.md), [runtime](local-b1.md).
