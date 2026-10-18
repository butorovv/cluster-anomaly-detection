# Контрольная точка №1: оборудование и пригодность модели

18.10.2026. **Этапы I–III выполнены. Переход к IV–X остановлен до согласования.**
Причина — существенная неприменимость Y на имеющихся аппаратных сведениях;
дополнительно требуется принять физический смысл MAD floor для R.
Это остановка, прямо предусмотренная ТЗ этапа 2, а не завершённый групповой алгоритм.

## 1. База и защищённые входы

Ветка `feat/group-detection-summit` создана от обновлённого `origin/main`
`3ba4698` (Merge pull request #8). Предыдущая рабочая ветка
`integration/research-4-3` была чистой; `origin/main..HEAD` перед переключением
пуст, `git branch -r --no-merged origin/main` пуст. Все удалённые ветки,
известные после fetch, включены в main; дополнительных необходимых коммитов
не обнаружено. PR №1–8 проверены по merge ancestry.

Изучены исходные mathematical spec, hardware reference, next-stage decisions,
evaluation protocol, research-4.3, `internal/local`, domain F18, reader/experiment
и существующие statistical/research functions. Формулы взяты из proposal v1,
без нового поиска признаков/порогов. Переиспользован исследовательский
`tools.context.context_stats.quantile` (inverted empirical CDF).

Полный manifest SHA до/после:
[D1 report](group-detection-d1-final/README.md#зафиксированные-входы),
[JSON](group-detection-d1-final/diagnostics.json).
Prepared `cf3fa634…`, statistical `36da27a4…`, IF `6aa1ca4f…`,
raw `7b6bcb90…` совпали с историческими SHA. Prepared D1 сверён по всем
829440×18 значениям с неизменным historical D1.bin.
Исходный F18, B1, IF, исторические профили и research-4.3 не редактировались.
Данные D2/D3 для нового исследования не анализировались.

## 2. Полная аппаратная таблица и F18 mapping

- [Нормализованный CPU/GPU/PSU реестр и 288 строк hostname](summit-hardware-inventory.md).
- [Машиночитаемый equipment/host inventory](../configs/summit-hardware-reference.json).
- [Паспортный эталон с первичными источниками](summit-hardware-reference.md).
- [Соответствие F18 и исследование дополнительных raw fields](hardware-to-f18-mapping.md).

Для точного CPU SKU/MTM, GPU P/N/cap/firmware и PSU FRU выбранных хостов
подтверждения нет. Типовой POWER9 22-core / V100 SXM2 подтверждён; различие
standard/high-memory известно для системы, индивидуальное соответствие — unknown.
Кандидат GTW не смешан с GTH/GTX, кандидат FSF069 не присвоен 288 узлам.

Обновление топологии основано на явной схеме авторов: a01…a16 задают cabinet
column/row, n01…n18 — позицию снизу. Это сильнее прежнего чисто логического
разбиения, но не доказывает общий electrical/cooling fault domain.

## 3. Заключение о Y и подтверждённые ограничения

**Список sensor-compatible hard bounds, разрешённых для бинарного Y, пуст.**
В JSON `approved_sensor_bounds=[]`, `y_status=unknown`; nominal/reference и
not_applicable записи не могут дать Y=false. Факт отсутствия границы не является
отрицательным аппаратным голосом. GPU/CPU/PSU нельзя называть исправными по нему.

300 W SXM2 — board specification, не удостоверенный installed-cap/sensor bound.
PCIe thermal limits установлены, но относятся к другой модификации. CPU mean
temperature не измеряет отдельный core maximum. PSU AC input нельзя напрямую
сравнить с 2200 W DC; эффективность чужого tested PSU не закрывает этот пробел.
Строгие границы не восстановлены из min/max или Q99 D1. Таблица D1 distributions
позволяет проверить единицы и диапазоны, но не определяет физическую допустимость.

Raw дополнительные `node_state`, `xid`, `label`, job metadata, GPU memory temp
и CPU min/max присутствуют; caps, FRU, alarms/thresholds отсутствуют.
В D1 выбранных хостов `Powered On`, label=0, xid=-1 во всех 829440 строках.
Это не независимая разметка отказов и не заменитель Y. F18 не расширен.

## 4. Диагностика 10D и математическая пригодность R/B

Все числа и полные matrices/spectra:
[D1 diagnostics](group-detection-d1-final/README.md).

| Проверка | Результат | Вывод |
|---|---|---|
| Фиксированные группы | 16×18, 2880/2880 full ticks каждая | Пропусков D1 нет; composition не меняется |
| Групповой вектор | 5 means + 5 population spreads, d=10 | Размерность сохранена |
| B covariance | ddof1, finite PSD, rank=10 во всех 16 | Алгебраически пригоден |
| Condition после normalization | 261.266…844.752 | В этой проверке признаков численной непригодности нет |
| Welford covariance crosscheck | max relative error 2.00e-15 | Согласован с независимым centered calculation |
| Moore–Penrose reconstruction | max relative error 1.06e-14 | Численно устойчив в исследуемом D1 |
| MAD floor B | 0/160 | Floor не влияет на нормализацию B этого D1 |
| MAD floor R | 4/1440, все GPU mean °C | Есть существенный вопрос физической интерпретации |
| R и B D1 strict Q99 | По 28 positive ticks каждой группы | In-sample calibration, не fault FPR |
| Lag-1 group coordinates | -0.138…0.835 | Ticks не независимы; N=2880 не effective sample size |

Четыре zero-MAD host channels: a02n09, a02n10, a09n05, a11n12.
При неизменном floor 1e-4 °C максимальные |z| — 166.7, 1666.7, 47500 и
49666.7 соответственно. Это конечные числа, не overflow; но 0.01 °C может
дать z=100. Floor не является sensor resolution или physical alarm.
Двуххостовое правило R смягчает единичный экстремум, но само по себе
не решает вопрос шума/дискретности. Значение floor не увеличивалось.

На D1 нет rank-блокера, основания автоматически менять d=10 на d=5 нет.
N≥11 — алгебраический минимум выполнен. Научная достаточность одного 8h
фрагмента для других дней не доказана; нет утверждённого coverage/ESS критерия.
Зависимость R/B на D2 ещё не оценена. Два статистических критерия не объявляются
независимыми голосами. Новый Go numerical parity ещё предстоит после согласования.

## 5. Рекомендуемая конфигурация первого алгоритма — для согласования

Сохранить proposal v1: 5 host channels, 10D mean/spread, фиксированные полные
18 F18, temporal host medians/MAD, R second-largest разных хостов одного
канала/знака, per-group D1 Q99; B robust normalization, Welford ddof1,
SVD rcond1e-12, rank<10→unknown, strict D1 Q99. Не вводить ridge/feature dropping.

Рекомендуется **preliminary R+B**, `Y=unknown`, `criteria_incomplete=true`,
общий hardware-confirmation status `insufficient_criteria`; не объявлять
аппаратной неисправностью и не смешивать с full 2/3 при применимом Y.
Существующие формулы трёхзначного vote2 сохраняются; выбор policy фиксируется
отдельно. Новая научная версия модели пока не заморожена как approved.

После согласования: δ=0 основной, 10/30/60 s sensitivity; causal trailing TTL,
unknown прерывает историю/событие, gap merge=0. B1 и его пороги неизменны,
S=a/n и E coverage-weighted — только annotations, без обязательного gate.
D1 fit, D2 research; D3 не использовать для параметров. Нужны будущие Go
contract tests, offline CLI, numerical parity, D2 event/evidence outputs,
графики и 4/8/16-group benchmarks. Они ещё не реализованы.

## 6. Открытые решения

1. Разрешить ли переход к реализации при пустом наборе Y bounds в описанном
   preliminary R+B / insufficient_criteria режиме? Альтернатива — ждать
   hostname→SKU/FRU/caps и BMC sensor bounds; искусственного Y не будет.
2. Принять ли floor 1e-4 W/°C именно как численное соглашение R с показанными
   четырьмя zero-MAD координатами? Изменение требует новой версии спецификации
   на основании D1/физики, без D2-подбора; автоматически менять его нельзя.
3. Считать ли имеющийся D1 достаточным для первого **исследовательского**
   прототипа с оговорками одного дня, либо требовать новый unused day/иной
   заранее заданный критерий достаточности? 10D rank и coverage уже проверены.

Общие вопросы версии 17.10 (δ/TTL segmentation, R rule, B full-rank policy)
сохранены в [next-stage-decisions](next-stage-decisions.md); предложения ТЗ
применяются после решения этой обязательной контрольной точки.

## 7. Наблюдаемые проверки и роли

- `go test ./...` — exit 0.
- `go build ./...`, `go vet ./...` — exit 0.
- Python regression + пять новых arithmetic tests: 115 passed, 5 skipped.
  PostgreSQL (5) без TEST_DATABASE_URL; replayer binary отдельно собран,
  cross-language e2e выполнен с synthetic fixtures (не новый D2 эксперимент).
  Первые попытки упёрлись в sandbox TEMP; успешный запуск использовал TMP/TEMP
  и pytest basetemp внутри `.cache/` проекта. Продуктовый код/ACL не менялись.
- Реальный D1 расчет — exit 0; protected input SHA before=after.
- Повторный D1 расчёт в новом `.cache/group-checkpoint-reproduction-01`:
  точное совпадение всех group medians/MAD/covariance/spectra/pseudoinverse/Q99,
  distributions, raw D1 summary и входных SHA. JSON inventory содержит ровно
  те же 288 hostname; approved Y bounds пусты. Изменённый annotation SHA
  спецификации отражает только добавленное заключение/уточнение топологии,
  формулы исходного proposal v1 сохранены.
- Arithmetic fixtures: physical aggregation/population spread, zero MAD floor,
  rank1/rank0→unknown, full rank covariance с известным ответом, missing/N<11.

Фактически запущены основной Orchestrator (`gpt-6.1-sol/high`, **configured**
по проектному config, runtime metadata не подтверждены) и один проектный
Inspector (`gpt-6-luna/low`, **configured**, режим docs). Inspector исследовал
первоисточники без записи; выводы/интеграция проверены главным. Другие роли
и каскадное делегирование не запускались. Read-only инструкция роли не
заявляется технической изоляцией runtime permissions.

Полное ТЗ этапа 2 **не завершено**: detector/state machine/D2 experiments,
performance и итоговые D2 графики отложены по условию остановки пользователя.
