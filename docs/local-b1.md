# Локальный B1: исполняемый контракт

Этап 1, 17.10.2026. Один сохранённый общий IF, индивидуальный порог каждого
hostname. Это текущий локальный runtime; историческая калибровка A0 по D2
остаётся исследованием и не используется новым детектором.

## Модель и происхождение порогов

`internal/local` применяет неизменённый `analysis.IsolationForest.Score` к F18.
Лес: 100 деревьев, sample size 256, depth 8, seed 42; нормализация общая по D1.
Для каждого хоста `theta[h] = EmpiricalQuantile(D1_scores[h], .99)`;
решение строго `score > theta[h]`. Используется существующий эмпирический
квантиль проекта; равенство порогу означает норму. Новый компонент не обучает IF.

В `configs/local-b1.summit-20220118.json` сохранены 288 проверенных порогов
из `results/context-v1/thresholds.json`, по 2880 D1-score на хост.
Импорт проверяет metadata, неизменность трёх входных SHA, SHA D1.bin,
полную сетку D1 и точное совпадение каждого порога с Q0.99 экспортированных
A0-score. Повторный расчёт score при импорте не нужен. Отдельный реальный тест
независимо пересчитывает D1-score замороженным лесом и сверяет все пороги.

| Идентификатор | SHA-256 |
|---|---|
| Prepared day | `cf3fa634448b7147209bebf3b1c20a1a031be5c047678083adda10581ff562e7` |
| Статистический профиль | `36da27a4a4f485baa4b1b1b899c26a36efc15401327fd85abc3d63ea3c1ade80` |
| IF | `6aa1ca4f2f76b56418aafaa1ea25e6812a3b9fdcc0d309aeed44dc1db03f2da3` |

Dataset ID — `prepared-sha256:<SHA>`. Идентификаторы моделей — SHA файлов целиком,
поэтому даже семантически равнозначная перезапись JSON требует нового связанного
профиля. Формат `local-b1-v1` хранит D1 `[2022-01-18T00:00Z,08:00Z)`, .99,
строгое сравнение, hosts, F18 order, counts и provenance. UTC остаётся явным
неподтверждённым допущением источника (`timezone_verified=false`).

`OpenModels` использует существующие проверки prepared/manifest, статистического
профиля и IF, затем `NewDetector` сверяет все binding-поля B1. Конструктор делает
снимки леса и таблиц: последующее изменение объектов вызывающим кодом не меняет
решение. Чистый `NewDetector` — API для уже проверенного загрузчиком binding;
проверка файловых SHA находится в `OpenModels`. Модели следует держать неизменными
в течение offline-запуска; это не транзакционная файловая система.

## Результат

`Evaluate(domain.TelemetryRecord)` возвращает timestamp, hostname, group_id,
nullable anomaly_score/individual_threshold/is_anomaly, is_available,
diagnostic_status и необязательное diagnostic. Group ID проверяется по hostname,
а не принимается как независимое свидетельство физической топологии. Timestamp
сохраняет переданное представление времени; prepared-путь использует принятое UTC.

| Статус | Доступность решения | Значение |
|---|---|---|
| normal / anomaly | true | Конечный score, порог, бинарное решение |
| incomplete_f18 | false | Согласованная маска, но есть NaN/Inf/отсутствующий признак |
| unknown_host | false | Хоста нет в inventory профиля |
| missing_threshold | false | Известный хост с 0 пригодных D1-состояний; score может быть доступен |
| invalid_observation | false | Неверная identity/time или маска противоречит F18 |
| scoring_error | false | Ошибка вычисления; offline-команда завершает запуск ошибкой |

`corrupt_profile` и `incompatible_model` — ошибки загрузки до inference,
с диагностическим JSON в stderr и ненулевым exit code. Пропавший порог у хоста
с положительным D1 count означает повреждение профиля, а не допустимый fallback.
Нулевой count не подменяется глобальным порогом. Nullable boolean необходим,
чтобы отсутствие решения не превращалось в `false`; `is_available` означает
доступность локального решения, а не только присутствие строки.

## Offline-команда

Из корня репозитория, при наличии прежних prepared и моделей:

```powershell
go run ./cmd/local --window D2 --summary-only
go run ./cmd/local --window D2 --output <NEW_EXTERNAL_FILE.ndjson>
```

По умолчанию используются пути из таблицы и `summit-D1-pilot/manifest.json`.
Их можно задать `--input`, `--manifest`, `--statistical-profile`,
`--isolation-profile`, `--b1-profile`. Вывод: строки `local_result` и завершающая
`local_summary`; `--summary-only` оставляет одну summary с binding, SHA B1,
coverage, counts, per-host counts и временем вычисления. Неполный вывод без
summary или с ненулевым exit code не считается завершённым запуском.
Файловый вывод и создание профиля используют O_EXCL, не перезаписывают файлы.

Воспроизведение нового профиля в **новый** внешний файл:

```powershell
go run ./cmd/local --build-profile <NEW_EXTERNAL_PROFILE.json> --import-context results/context-v1
# Альтернатива без исследовательского экспорта: только score по D1, без обучения IF.
go run ./cmd/local --build-profile <ANOTHER_NEW_EXTERNAL_PROFILE.json>
```

Build фиксирует D1 независимо от inference-window, отклоняет D2/D3,
повторные/несортированные timestamp хоста и записи вне сетки 10 s.
Пропущенные полные состояния уменьшают counts; любой такой новый профиль требует
анализа достаточности D1. Минимальная версия не вводит произвольный coverage-порог.
Различие provenance двух способов не мешает точному совпадению thresholds.

## Проверки

Быстрые проверки: `go test ./...`, `go build ./...`, `go vet ./...`.
Большая проверка отделена:

```powershell
$env:LOCAL_B1_REAL='1'
go test -count=1 -v ./internal/local -run TestRealB1D2MatchesResearch
Remove-Item Env:LOCAL_B1_REAL
```

Она требует локальных prepared, двух моделей и сохранённого context-v1.
Проверяет все пороги, D2 829440 доступных решений / 14341 срабатывание и
независимое D1-воспроизведение. Это регрессия относительно исследования;
14341 не является целевой функцией или оценкой качества неисправностей.
Python research tests включены в pytest.ini; явная команда:

```powershell
python -m pytest -p no:cacheprovider tools/dataset/tests tools/diagnostics/tests tools/context/tests tests/e2e
```

DB-тесты требуют отдельно разрешённого `TEST_DATABASE_URL`. Обычный B1 не
использует PostgreSQL. Рабочая память inference — лес + decoder Parquet + counters;
пороговая таблица O(H). Независимый D1 rebuild дополнительно хранит O(H*T1)
скалярных score для точного квантиля. Стоимость score O(trees*depth) на запись.
