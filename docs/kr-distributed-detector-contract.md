# Проект контракта вычислительного ядра для распределённой КР

18.10.2026. **Архитектурное предложение, не реализованные сервисы.**
Математическая основа: `summit-group-research-v1`,
[научное заключение](nir-group-model-scientific-summary.md),
[действующий offline CLI](group-detection-runtime.md).

```text
Telemetry Replayer
       |
       v
      Kafka
       |
       v
 Group Worker(s)
       |
       v
 Group Detection / Events
       |
       v
      Master
       |
       v
 Cluster-level Analysis
```

Ни Kafka, ни Worker/Master, HTTP или GUI в этом этапе не создаются.

## 1. Инвариант математической эквивалентности

Пусть canonical input — одинаковые уникальные TelemetryRecord с F18 masks,
полным фиксированным inventory, границами окна и явными отсутствующими ticks.
При одинаковых SHA моделей/конфигураций и восстановленном event-time порядке
offline и distributed должны выдавать **одинаковые R/B/Y states, witnesses,
candidate states, intervals и event IDs**. Счётчики IF/availability и E совпадают.
Float64 scores сравниваются в заранее утверждённых допусках; на контрольном
Summit baseline бинарные решения должны совпасть точно, особенно около Q99.

Processing/emission latency, broker offsets и порядок доставки результатов
разных групп могут отличаться. Watermark wait не добавляется к logical
confirmation_delay_seconds и не меняет δ. Если политика поздних данных
исключила записи, canonical input изменился: эквивалентность проверяется
против offline **того же accepted-input ledger**, а не произвольно полного Parquet.
Для строгого сравнения с полным исходным файлом нужна гарантированная полнота
доставки до финализации или отдельный replay-run с поздними записями.

## 2. Данные Worker и партиционирование

Предлагаемый envelope `telemetry-v1`:

| Поле | Назначение |
|---|---|
| schema_version, run_id, source_dataset_sha256 | схема и неизменная идентичность источника/запуска |
| group_id, group_inventory_sha256, topology_epoch | membership по зафиксированному inventory |
| hostname, event_time, step_seconds=10 | реальный host, timestamp UTC с сохранением assumption flag |
| f18[18], availability_mask, valid | фиксированный порядок; missing coordinate=null/mask=0, не 0 |
| source_record_id, producer_id, sequence, payload_sha256 | retry/dedup/целостность |
| feature_schema_sha256, profile_bundle_sha256 | обязательная совместимость с математическим ядром |

Kafka key предлагается `(run_id, topology_epoch, group_id)`. Все записи группы,
progress markers и completions должны попадать в ту же partition. Число
partitions/назначение групп фиксируется на run; изменение требует нового epoch
и контролируемого перехода, не перемешивания двух историй одного Engine.

Членство определяется **списком hostname в профиле**, а encoding hostname
служит проверкой согласованности. Unknown host, несовпадающие group/schema/model
не принимаются как нормальные измерения. Реальные a01–a16 не заменяются
перестановочными p01–p16: те были отдельным исследованием.

Порядок Kafka partition является порядком log offsets, а event-time может
отставать/опережать при нескольких producers. Поэтому sort/barrier необходим
на уровне приложения. Основание — разделы Consumer Position/Delivery Semantics
[официального Kafka Design](https://kafka.apache.org/41/design/design/).
Версия Kafka/Go client ещё не выбрана и не закреплена этим предложением.

## 3. Неизменный bundle профилей

Bundle содержит dataset/F18 schema, список/порядок всех hosts, окно D1,
assumed_timezone и verified flag, SHA IF, F18 normalizer, B1 thresholds,
group-profile-v1, hardware registry и математической конфигурации.
Групповой профиль: пять host median/MAD/scales, R Q99; 10D normalizer,
normalized center, covariance/pseudoinverse, singular/eigen spectra,
effective rank/reason, B Q99, sample counts и input bindings.

Workers **не обучают** IF/R/B и не корректируют пороги. Bundle загружается
вне hot path существующими валидаторами. Смена профиля требует нового run
либо явной epoch границы с новым Engine; TTL через границу не переносится.
Одновременное смешение B1 одной версии и R/B другой запрещается.

Training-dataset SHA профиля и replay-source SHA запуска — разные роли.
В golden Summit replay они ссылаются на тот же исторический prepared day.
Для нового дня нужны отдельный source manifest и явная проверка schema/hosts/
timezone compatibility; training SHA не переписывается и модель не обучается
заново молча. Нынешний `cmd/group` ограничен историческими SHA и окнами D1/D2;
поддержка нового inference source потребует отдельной адаптации загрузчика.

Чтобы сохранить ID baseline, координатор передаёт всем Workers один и тот же
run_id, рассчитанный по canonical serialization существующего offline CLI:
SHA256(JSON `[group.Version, profileSHA, inputHashMap, groupUniverseSize, window]`).
Worker не пересчитывает его по своему подмножеству входных файлов. Необходимо
сохранить точные JSON/time правила Go; сторонняя сериализация с иным byte order
может дать другой hash. Для нового streaming source нужен отдельный
версионируемый source manifest, а не подмена SHA исторического Parquet.

## 4. Вычисления на группе

Для каждого t Worker собирает фиксированные 18 слотов. Обработка после barrier:

1. Проверить источник, schema/bundle, group/host, duplicates, F18 mask/finite/grid.
2. Получить LocalResult B1 существующим `internal/local` по доступным host states.
3. Если все 18 полны — пять физических агрегатов и 10D; вызвать сохранённые R/B.
   Иначе R=B=unknown, сохранить missing hosts и известные Q99.
4. Независимо вызвать hardware module по approved bounds. Сейчас Y unknown
   с `no_approved_sensor_bounds`; номинал не применяется как bound.
5. Последовательно по event time вызвать Group Engine, выбранный δ и frozen
   Y-policy. Получить raw/temporal states и GroupEvent updates/closure.
6. Сохранить результат и state/offset согласованно; только затем подтвердить input.

Суммирование хостов — в порядке profile inventory, float64 и существующее Go-ядро.
Нельзя делать несогласованное parallel reduction по приходу сообщений:
неассоциативность float64 способна изменить strict-boundary решение.
Нельзя усреднять только доступные 17 вместо 18 или интерполировать пропуск.

В PR №1 КР выделен `group.EvaluateGroup(*GroupProfile, Tick, *Hardware,
*local.Detector, *Timing) (Raw, error)`: тот же порядок 18 хостов и вызовы R/B/Y/IF,
без временного состояния и вне-группового контекста. Нужен заранее проверенный
профиль; изменять модели/records во время вызова нельзя. Nil Timing допустим.
Неполные F18 сохраняют unknown; некорректные inventory/grid/record identity
отвергаются. Offline `Evaluate` вызывает это ядро для 4/8/16 групп и затем
прежний `AnnotateOutside`. До annotation `OutsideGroups`, `OutsideS`, E равны nil;
outside counts в JSON — null, а не фиктивный ноль. После annotation формат
offline Raw сохраняется.

`group.LoadBundle(BundleFiles)` загружает private frozen-модели без Parquet;
обязателен доверенный ProfileSHA256. Physical Path и исторический InputKey
разделены. Сохраняются все SHA/F18/inventory/normalizer/envelope проверки.
`Bundle.EvaluateGroup` не раскрывает изменяемые профили, `Bundle.RunID` использует
прежние logical keys. Фактический source отдельно проверяет `Bundle.OpenSource`
по bytes SHA/manifest/topology/timezone. Loader не подтверждает наличие/полноту
потока телеметрии. Kafka, assembler, Worker/Master и recovery остаются будущими
этапами; [применение и parity-проверка](group-detection-runtime.md#api-одной-группы).

## 5. GroupResult и GroupEvent

`GroupResult-v1` на каждый group/tick: run/model/schema/inventory IDs, raw
R/Y/B (state, reason, nullable score/threshold), 10D vector при полноте,
complete/expected count и missing mask, R defining pair/all witnesses,
Y device evidence, LocalResult/IF available/anomalous counts, S,
temporal occurrences/witness times, vote2, preliminary/full candidate,
criteria_incomplete и hardware_confirmation.

На Worker вычисляется **S текущей группы**, вне-групповой E — только на Master.
Worker не должен выдавать E=0 при отсутствии других групп.

`GroupEvent-v1` следует существующему Event: run_id,
ID=SHA256(`run_id/group/delta/detected_time_UTC`), first evidence, detected,
last positive, closed, positive/raw/TTL ticks, duration, delay,
missing/window/left censoring, mode, IF/zero-MAD support и witness union.
При неизвестном Y обязательны preliminary, criteria_incomplete=true,
hardware_confirmation=insufficient_criteria. Данные указывают статистический
сигнал; hardware fault label допускается лишь с независимым provenance.

Обновление открытого события предлагается как versioned upsert с тем же event ID
и monotone processed_tick/revision; закрытие — одно terminal update.
Event start/close не зависит от времени отправки. Unknown/gap/mode switch
и terminal Flush сохраняют offline семантику, без склейки через пропуски.

## 6. Watermark и bounded lateness — предложение

Пока не реализовано. Кандидат инженерной политики: L=30 s как первоначальный
buffer budget, требующий проверки на реальном распределённом transport replay.
Это **не δ**, не новый статистический порог и не результат оптимизации D2.

Для набора producers P_g, известного до run, пусть E_pg — наибольшее
полученное producer progress/event time с sequence audit. Предлагается
W_g=min_{p∈P_g}(E_pg−L), W не убывает. Финализируется tick t только при t<W_g.
Записи до финализации упорядочиваются по timestamp→profile host order.
При известном конечном потоке producer отправляет EndOfSplit после всех своих
record sequences; после подтверждения всех producers можно завершить окно.

Неактивный producer не исключается молча: остановка progress останавливает
watermark. Wall-clock timeout может породить диагностический transport timeout;
принудительное продвижение разрешается только отдельной согласованной политикой,
с explicit missing/censoring и новым accepted-input ledger.
Сам TimestampComplete нынешнего Replayer подтверждает отправленные строки,
**не полноту всех 18 хостов**. Нужны expected inventory, observed sequence/count
и progress каждого producer; один barrier от одного producer не заменяет остальных.

Сообщение с event_time≤last_finalized_tick отправляется в late/quarantine
ledger, не вносится задним числом в закрытый Engine. Для корректировки нужен
новый revision run с полной event-time сортировкой и сопоставлением прежних
результатов. Строгий finite-file replay может ждать все EndOfSplit, а bounded
online replay — завершаться по L; их raw input полнота должна сравниваться явно.

Различие event/processing time и допуск out-of-order также описаны в
[Kafka Streams Core Concepts](https://kafka.apache.org/41/streams/core-concepts/).
Это источник терминов; применение Kafka Streams не предлагается как уже выбранный runtime.

## 7. Повторы, конфликты и пропуски

Canonical record key=(run,epoch,group,hostname,event_time). Retry с тем же
payload SHA устраняется до математического ядра. Одинаковый ключ с другим
payload — конфликт источника: fail/quarantine run, не «первый/последний победил».
Существующий offline reader не допускает duplicate host/time; dedup транспортных
retries не означает разрешение конфликтных повторов в canonical input.

После watermark отсутствующие host slots/ticks материализуются как missing.
Все отсутствующие ticks должны быть представлены, включая полностью пустую
группу. Unknown R/B разрывает событие; известный отрицательный Y из отсутствия
границ не создаётся. Системное отсутствие данных отделяется от отсутствия
аномалии. Data availability и topology/model mismatch — разные причины.

Выходной ключ GroupResult=(run,group,δ,t), Event=(run,event ID).
Повторная доставка того же deterministic payload — идемпотентный upsert;
иной payload для terminal key — ошибка воспроизводимости, не тихая замена.
Хранилище/consumer должны исключать повторный подсчёт событий.

## 8. Сбой Worker и восстановление

Для первого корректного прототипа достаточно **детерминированного replay от
начала split** на том же bundle и canonical input, с идемпотентным sink.
Это восстанавливает даже открытое событие/TTL без новых методов ядра, но может
быть дорого. В `group.Engine` сейчас нет public Snapshot/Restore API;
автоматическая сериализация его приватных полей не считается решением.

Будущий versioned checkpoint должен включать offset/sequence/dedup horizon,
watermark, reorder buffer, последний обработанный tick, latest positive/unknown
и host witnesses каждого метода/δ, open Event/counters, run/bundle/inventory SHA.
Checkpoint несовместимой версии не загружается. Новый owner не обрабатывает
partition параллельно прежнему; необходим ownership fencing/epoch.

State/output и consumed offsets надо фиксировать согласованно. Kafka transactions
позволяют связать Kafka outputs с offsets, но внешнее хранилище требует собственной
transaction/outbox/idempotency схемы. Commit offsets до надёжного результата
может потерять решение, после результата — дать retry. Общая гарантия не возникает
только из настроек producer. Это следует из разделов Message Delivery Semantics /
Using Transactions [Kafka Design](https://kafka.apache.org/41/design/design/);
конкретный Go client и persistence adapter выбираются позже.

## 9. Master и кластерный контекст

Master принимает GroupResult всех ожидаемых групп одной run/epoch/model version.
Он ведёт event-time barrier/cluster watermark W_cluster=min W_g, учитывая
реальную coverage. Для t из доступных local counts вычисляет S_outside и E,
сохраняет состав outside groups, available/expected hosts и incomplete cluster flag.
Missing group не заменяется нулевой anomalous fraction.

Отдельный committed missing/result marker позволяет закончить tick при
недоступности группы; молчание transport не является таким marker.
Неполный Master snapshot не меняет group Event и не подавляет его автоматически.
Master показывает локальные/многогрупповые/общие эпизоды, но не объявляет их
hardware faults. IF/E остаются annotations; групповые R/B заново не обучаются.

## 10. Приёмка будущей реализации

Golden replay: 288 hosts, 16 групп, те же source/model/profile SHA, D2, δ=0.
Требуются 899 R+, 3260 B+, 682 candidates, 285 events, Y unknown, 14 341 B1+,
совпадающие witness values/IDs/интервалы и integer IF counters.
Дополнительные δ=10/30/60 сравниваются с прежними golden tables, без выбора нового δ.

Transport fixtures: переставить delivery order в пределах L, добавить точные
retries, пустые host/group ticks, worker restart внутри длинного события,
restart до/после commit, смену partition owner, late>L и конфликтный duplicate.
Сначала восстановить одинаковый accepted canonical stream; только затем
сравнивать mathematical outputs. Unknown/censoring и duplicate-free event IDs
обязательны; processing latency измеряется отдельно. Near-Q99 случаи должны
сохранять строгий знак и показывать float64 tolerances, без изменения порогов.

До такого прогона эквивалентность является **требованием проекта**, а не
достигнутой характеристикой распределённой системы. Решения о L, progress/barrier,
late policy, persistence и checkpoint формате требуют отдельного задания.
