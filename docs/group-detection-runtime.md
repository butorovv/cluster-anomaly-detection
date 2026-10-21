# Offline групповой runtime Summit

Исследовательская версия `summit-group-research-v1`. Библиотека — `internal/group`,
CLI — `cmd/group`. Результаты: [реальный D2 отчёт](group-detection-real-d2-results.md).
Контракт: [математическая спецификация](group-detection-mathematical-spec.md).

## API одной группы

`group.EvaluateGroup` возвращает Raw одной группы без outside IF/E и без Step
временного Engine. `group.Evaluate` остаётся offline-путём и добавляет прежний
межгрупповой контекст. Численные функции и event segmentation не меняются.
До `AnnotateOutside` outside counts сериализуются как null; Go int-поля этих
counts не интерпретируются, пока `OutsideGroups == nil`.

Для inference без исторического Parquet: `group.LoadBundle(BundleFiles)`.
`ProfileSHA256` берётся из доверенного manifest запуска, а не вычисляется
для принятия произвольного неизвестного профиля. Для пяти model/config assets
задаются physical `Path` и прежний логический `InputKey` из `Profile.InputSHA`;
`PreparedKey`/`ManifestKey` именуют два оставшихся source hashes. Все семь
bindings обязательны. Loader проверяет bytes, метаданные и numerical validators,
не обучает модели и не открывает telemetry. Models остаются private/immutable.
`Bundle.OpenSource(input, manifest)` отдельно проверяет фактический replay source.

`Bundle.RunID(groups, window)` и общий `group.RunID` сохраняют Go JSON v1 identity.
Смена физических путей не меняет ID при сохранении исторических logical keys.
Старый CLI продолжает применять свои проверки входов и прежние пути/опции.

Opt-in тест нового API против полных pre-change offline outputs:

```powershell
$env:GROUP_REAL_ROOT='C:\path\to\existing-readonly-assets'
$env:GROUP_REAL_REFERENCE='C:\path\to\pre-change-D2-output'
go test -count=1 -v ./internal/group -run TestRealPerGroupD2Parity
```

Reference должен содержать `raw.ndjson`, `temporal.ndjson`, `events.ndjson`
от прежнего CLI v1, D2/16 групп/всех четырёх δ. Тест сравнивает полные keyed
payload и float64 точно на той же Go-среде, а не только итоговые counts.
Отсутствие переменных даёт явный SKIP; недоступный указанный asset — FAIL.
Вычисления не создают Worker/Kafka/HTTP и не меняют frozen-профили.

## Запуск

Из корня репозитория, с существующими неизменными prepared/manifest,
statistical/IF моделями и B1, указанными в `docs/local-b1.md`:

```powershell
go build -o bin/group.exe ./cmd/group
bin/group.exe --profile configs/group-profile.summit-v1.json --window D2 --output results/NEW_D2_RUN
```

Сохранённый group profile уже обучен на D1. Для независимого воспроизведения
в новый каталог, без изменения старого профиля или леса:

```powershell
bin/group.exe --fit --output results/NEW_D1_FIT
python tools/groupdiagnostics/parity.py --run results/NEW_D1_FIT --output results/NEW_D1_FIT/parity.json
```

`--fit` всегда использует только фиксированный D1 `[00:00,08:00)`; после fit
вычисляет D1 результаты. Инференс поддерживает `--window D1` и `D2`.
`D3` намеренно отклоняется. Все пути входов видны через `--help`:
`--input`, `--manifest`, `--statistical-profile`, `--isolation-profile`,
`--b1-profile`, `--hardware`, `--config`. Не заменять входы для улучшения D2.

Каждый запуск требует **новый** `--output`. Existing directory или файл не
перезаписывается. Неполный каталог без успешного exit=0 и summary не считается
завершённым результатом. Для parity нужны NumPy 2.3.5 и PyArrow 26.0.0 из
существующего окружения; packages во время исследования не обновлялись.

## Артефакты Go

| Файл | Содержание |
|---|---|
| profile.json | Только fit: 16 профилей R/B, полные median/MAD, covariance/SVD, Q99, provenance |
| raw.ndjson | На каждый group tick: raw R/B/Y, score/threshold, host values, defining pair/all witnesses, zero-MAD, complete/missing, все 18 LocalResult B1, S/outside/E |
| temporal.ndjson | Четыре δ: occurrence R/Y/B, witness times, vote2, preliminary/full candidate и first evidence |
| events.ndjson | Закрытые GroupEvent с уникальным ID/run ID, first/detected/last-positive/closed, duration/delay, censoring, IF/zero-MAD counts и union hosts |
| summary.json | Input SHA before/after, group profile SHA, run identity, build/VCS metadata, counts, kernel timers и sampled heap |

Raw schema использует `positive`, `negative`, `unknown`; неизвестные score/
пределы — JSON null. Отсутствующие F18 не заполняются нулями. Полностью отсутствующий
tick тоже поступает в Engine как unknown. Duplicate/unordered rows отклоняются.
IF score применяется только существующим `internal/local.NewDetector`.

При неизвестном Y событие предварительное: `criteria_incomplete=true`,
`hardware_confirmation=insufficient_criteria`. `mode=full` при доступном Y
также **не** означает подтверждённую аппаратную неисправность: это только
доступность критериев и результат 2/3. Raw R-only/B-only сохраняются отдельно.

Временная память — последние positive/unknown каждого метода. Known negative
сохраняет ещё живое TTL-свидетельство; unknown его отменяет. Gap очищает историю,
mode change завершает старое событие. Begin/end split сбрасывает память.
`duration_grid_seconds` включает последнюю положительную 10 s ячейку;
`raw_coincident_span_seconds` — span raw совпадений, а `ttl_extension_ticks`
считает candidate ticks без raw совпадения. Первое/последнее событие может быть
left/right censored. Истинное время возникновения неисправности неизвестно.

`Flush(end)` завершает Engine на исключающей правой границе сетки 10 s;
после него `Step` отклоняется, повторный корректный `Flush` не дублирует события.
Если последний наблюдавшийся tick раньше `end-10s`, событие закрывается на
первом пропущенном tick с missing-censoring, а не на конце окна.

Каждое событие связано с полными входами/моделями через `run_id` и summary.
Физические свидетельства ищутся в raw по group и temporal witness timestamps,
включая positive перед detected time при δ>0. Для компактного опубликованного
набора доступны [r-evidence.ndjson](group-runtime-v1/d2/r-evidence.ndjson)
(все R-positive), temporal CSV с witness times и полный event JSON/CSV.

## Y и расширение реестра

`LoadHardware` читает только `approved_sensor_bounds`; equipment nominal
характеристики не используются в тестах. Пустой массив даёт unknown с
`no_approved_sensor_bounds`. Обязательны id, exact hostname, sensor F18,
device_model, unit, measurement_boundary, aggregation, source_url,
verified/compatible=true и конечная lower/upper граница. Поддерживаются W/AC,
W/DC, degC/core_temperature и degC/mean_core_temperature с `10s_mean`.
Конкретная совместимость и утверждение границ — обязанность независимого реестра,
не результат статистической калибровки. Equality не является превышением.

Устройство → host (любой positive; negative только непустой полный набор) →
group (минимум два **разных** positive hostname, иначе трёхзначная доступность).
Bounds копируются в модуль; последующая мутация вызывающим кодом не меняет их.
Пределы в возвращённых device evidence также копируются и не раскрывают
изменяемые указатели реестра.
Искусственные тестовые bounds находятся только в unit fixtures.

Y отделён от R/B. Будущее добавление verified bounds не требует изменения
математических коэффициентов R/B, но требует новой версии registry/run binding.
Замороженный CLI v1 отклоняет тихое изменение SHA registry/config/model;
обновление provenance должно быть явным, а не скрытым переобучением.

## Воспроизведение анализа и производительности

```powershell
python tools/groupdiagnostics/audit_runtime.py --run results/NEW_D2_RUN --output results/NEW_D2_RUN/audit.json
python tools/groupdiagnostics/analyze_runtime.py --run results/NEW_D2_RUN --output results/NEW_REPORT_ASSETS
python tools/groupdiagnostics/tables_runtime.py --input results/NEW_REPORT_ASSETS
python tools/groupdiagnostics/benchmark_runtime.py --binary bin/group.exe --output results/NEW_PERFORMANCE
python tools/groupdiagnostics/benchmark_runtime.py --binary bin/group.exe --full-only --output results/NEW_FULL_PERFORMANCE
```

Analysis создаёт PNG/SVG и source CSV/JSON в новом каталоге, не подбирает
параметры. Правило выбора примера записано в frozen config. Benchmark на Windows
измеряет process-lifetime peak working set, отдельно от Go sampled heap.
`--groups 4/8/16` выбирает вложенный scoring/outside universe без refit;
`--summary-only` убирает raw/temporal materialization, сохраняя events и summary.

Проверки: `go test ./...`, `go build ./...`, `go vet ./...`, стандартные Python
regressions, D1 parity и независимый D2 audit. Real B1:

```powershell
$env:LOCAL_B1_REAL='1'
go test -count=1 -v ./internal/local -run TestRealB1D2MatchesResearch
Remove-Item Env:LOCAL_B1_REAL
```

После первого D2 при финальной приёмке добавлены только проверки загрузки
covariance/inverse, защита Y от повторного hostname и сохранение Y-host witnesses
в full fixture-событиях, сохранение известных Q99 при unknown observation.
Коэффициенты/формулы и реальные R/B/Y решения не менялись;
финальный replay проверяет точное совпадение counts и всех events с frozen run.
