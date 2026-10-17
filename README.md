# Cluster Anomaly Detection

Начальный этап КР «Программная система выявления групповых аномалий в вычислительных
кластерах»: offline Summit → F18 D1/D2/D3 → PostgreSQL и Go Telemetry Replayer.
Offline-ядра Mahalanobis, компонентной физической модели и Isolation Forest
реализованы ниже; Worker, Master, Kafka, HTTP/GUI пока не реализованы.

**Текущий статус:** реальный Summit D1 (`20220118.parquet`, ClusterWise) скачан,
SHA256 и PyArrow проверены. Подготовлены 2 488 320 F18 states для 16×18 узлов,
в `cluster_anomaly_dev` импортированы все 44 789 760 измерений суток без дубликатов.
Go Replayer проверен на каждой реальной записи; Python/Go tests, build и vet прошли.
Группы a01–a16 предварительные, timezone UTC — явное непроверенное допущение.
Для дальнейших расчётов утверждено разбиение этого же дня на D1/D2/D3 по 8 часов;
описания прежнего трёхдневного workflow ниже сохраняются как история Builder.
Размеры, SHA256 и полнота локальной выборки сохраняются в prepared manifest;
команды и resume: [D1 pilot](docs/summit-D1-pilot.md).

## Математическое ядро НИР

Актуальное экспериментальное разбиение заменяет прежние три календарных дня:
один существующий prepared Parquet за 18.01.2022, D1 `[00:00,08:00)`, D2
`[08:00,16:00)`, D3 `[16:00,24:00)` в принятом UTC. Часовой пояс исходного
источника пока не подтверждён. Дополнительные Parquet и скользящие окна не нужны.
На интервал ожидаются 2 880 timestamp и 829 440 состояний 288 выбранных узлов.
Manifest исходного суточного файла сохраняется; его историческое имя
`D1.parquet` не означает, что для обучения используются все сутки.

Этап A реализован в `internal/analysis`: формулы (8)–(14) §§2.3–2.4 компонентной
РПЗ `НИР7_Буторов_РПЗ_07_10_2026_компонентная_модель.docx`. Параметры
нормализации, центр, ковариация, псевдообратная Gonum SVD и квантиль 0,99
оцениваются только по полным конечным состояниям D1. Ядро проверяет timestamp
на каждом обучающем проходе. Исходные F18 не изменяются. Метка Mahalanobis —
контрольный статистический ориентир, не разметка аппаратных неисправностей.
Инженерные соглашения вынесены в конфигурацию: `covariance-ddof=1`
(выборочная ковариация) и `svd-rcond=1e-12` (относительный допуск ранга).
Они сохраняются в профиле и не заявляются как утверждённые числа РПЗ.

`internal/replayer/WindowReader` фильтрует `[start,end)` поверх прежнего Reader,
сохраняя порядок, проверку дубликатов и доступность. Он не делает агрегации
по времени и не меняет Scheduler/TimestampComplete. `internal/experiment`
проверяет SHA-256 и порядок F18 manifest, фиксированную топологию и количество
отсчётов; `cmd/nir` собирает воспроизводимый статистический профиль и применяет
его к трём интервалам. PostgreSQL в вычислении не участвует. Проверка диска
требует минимум 5 GiB свободными плюс 64 MiB запаса.

```powershell
go run ./cmd/nir --input data/prepared/summit-D1-pilot/D1.parquet --manifest data/prepared/summit-D1-pilot/manifest.json --output results/statistical-20220118-8h-v1.json
```

JSON небольшой, сохраняется в исключённый из Git `results/`; существующий
результат не перезаписывается. Обучение и применение выполняются потоковыми
проходами по одному файлу; точные медианы/MAD требуют массивов отдельных
координат D1 в памяти, но не временных файлов телеметрии. Формулы, вырожденность,
границы интервалов, отсутствие D2/D3 в обучении, неизменность профиля при
inference и JSON round trip покрыты unit-тестами. Реальные шесть ранее
сохранённых снимков можно проверить отдельно:

```powershell
$env:NIR_REAL_SAMPLE=(Resolve-Path data/prepared/summit-D1-pilot/ten-minute-f18.json).Path
go test -v ./internal/analysis
```

Полная численная проверка этапа A завершена на **829 440 пригодных состояниях
D1**: ковариация 18×18 имеет ранг 18, порог `D²` равен
`77.70489690680702`, строгая контрольная метка сработала 8 294 раза.
Профиль сохраняется прежним `SaveNew`, загружается через `LoadProfile` и
проверяется до использования: конечность, положительная полуопределённость,
согласованность ранга и псевдообратной. Переполнение расстояния возвращает
ошибку. Численные результаты подтверждены независимым расчётом NumPy/PyArrow.
Методика, ресурсы и воспроизведение: [реальный профиль D1](docs/real-d1-statistical-profile.md).

Реальная проверка временных границ использует существующий суточный файл:

```powershell
$env:NIR_REAL_PARQUET=(Resolve-Path data/prepared/summit-D1-pilot/D1.parquet).Path
go test -v ./internal/experiment -run TestRealPreparedDayWindows -count=1
```

Для каждого из D1/D2/D3 подтверждены 829 440 состояний, 2 880 timestamp и
46 080 TimestampComplete без пересечений. Невыставленная переменная означает
SKIP, а явно выбранный недоступный файл — FAIL. Проверка шести снимков остаётся
отдельной от полного обучения D1. Этапы B/C и калибровка IF на D2 реализованы;
итоговые испытания и топологическая агрегация относятся к следующим мини-ТЗ.

## Isolation Forest — мини-ТЗ №3

**Текущий локальный runtime B1 (17.10.2026):** один сохранённый IF с
индивидуальными Q0.99-порогами каждого hostname, вычисленными только по D1.
`go run ./cmd/local --window D2 --summary-only` применяет проверенный профиль
`configs/local-b1.summit-20220118.json`. Результат различает аномалию, норму и
недоступность решения; D2/D3 не используются для подбора этих порогов.
Старые калибровки ниже сохраняются как история исследований.

Контракт, воспроизведение и отдельная реальная регрессия:
[local B1](docs/local-b1.md). Групповой алгоритм пока описан предложением:
[математическая спецификация](docs/group-detection-mathematical-spec.md),
[паспортный эталон](docs/summit-hardware-reference.md),
[протокол оценки](docs/group-detection-evaluation-protocol.md),
[решения для согласования](docs/next-stage-decisions.md).

`internal/analysis/isolation.go` реализует один общий лес для 288 узлов по F18.
Существующие median/MAD/scale из сохранённого статистического профиля D1
используются без переобучения. Независимые reservoir-выборки для каждого дерева
получаются за один потоковый проход D1; физические остатки в IF не входят.
По умолчанию `trees=100`, `sample-size=256`, `max-depth=8`, `seed=42`.
Чем выше score, тем аномальнее состояние. В мини-ТЗ №3 рассчитывается только
score; калибровка порога на D2 описана ниже. D2/D3 обучение леса не использует.

```powershell
go run ./cmd/isolation --statistical-profile results/statistical-20220118-8h-v1.json --trees 100 --sample-size 256 --max-depth 8 --seed 42 --output results/isolation-new-run.json
go run ./cmd/isolation --statistical-profile results/statistical-20220118-8h-v1.json --profile results/isolation-new-run.json --output results/isolation-new-reloaded.json
```

Первый запуск сохраняет лес, F18, окно обучения, SHA-256 датасета и исходного
статистического профиля, audit D1, распределение score и метрики ресурсов.
Загрузка проверяет эту связь и повторяет расчёт D1 без обучения; CLI требует
точного совпадения статистик. Результаты сохраняются прежним `SaveNew` в
исключённый из Git `results/`, существующие файлы не перезаписываются.
Реальные **829 440 состояния D1**, повторное обучение, reload и независимая
NumPy/PyArrow-проверка описаны в [отчёте IF](docs/real-d1-isolation-forest.md).

## Калибровка IF на D2 — мини-ТЗ №4

`cmd/calibration` загружает сохранённые модели D1 и обрабатывает только D2
`[08:00,16:00)` UTC. Порог выбирается среди различных наблюдаемых score по
максимальному F1 согласования с контрольными метками Mahalanobis. Бинаризация
строго `score > theta_IF`; при равном F1 выбирается наибольший порог.
Сортировка и проход блоками равных score дают `O(n log n)`; сравнение F1
выполняется точно по целочисленным счётчикам. Неопределённые метрики
сохраняются как JSON null. Ни одна модель D1 не переобучается.

```powershell
go run ./cmd/calibration --isolation-profile results/isolation-20220118-v1.json --statistical-profile results/statistical-20220118-8h-v1.json --output results/calibration-new.json
go run ./cmd/calibration --isolation-profile results/isolation-20220118-v1.json --statistical-profile results/statistical-20220118-8h-v1.json --calibration results/calibration-new.json --output results/calibration-new-reloaded.json
```

Результат содержит порог, confusion matrix, Precision/Recall/F1, число
IF-срабатываний, audit D2 и SHA-256 датасета/исходных моделей. `--calibration`
применяет сохранённый порог без поиска и проверяет совпадение результатов D2.
Реальный порог **0.6850838848387528**, F1ref **0.2294187530250363**;
это согласование статистических псевдометок, не диагностика аппаратных отказов.
Данные и результаты остаются в исключённых каталогах, D3 не используется.
[Технический отчёт и независимая проверка](docs/real-d2-isolation-calibration.md).

## Архитектура

```text
cmd/replayer                  entrypoint
cmd/worker, cmd/master         placeholders будущих приложений
internal/app                  composition root, config, slog, lifecycle
internal/modules/telemetry    domain, usecase ports, pgx repository
internal/replayer             reader, scheduler, sender/completion ports
internal/platform             config, logger, postgres pool
db/migrations                 канонический V1 + пять metric_type
db/demo                       optional учебные данные отдельно
db/queries/f18.sql             восстановление F18(node_id,timestamp)
tools/dataset                 Python offline inspector / builder / COPY importer
tests/integration, tests/e2e   реальные DB и cross-language проверки на фикстурах
data/raw, data/prepared        большие inputs/outputs, исключены из Git
```

Подробнее: [архитектурный контракт](docs/architecture.md),
[канонический SQL](db/README.md), [offline обработка](tools/dataset/README.md).
Raw — полный исторический архив. PostgreSQL хранит только F18 выбранных hosts.
Replayer читает prepared Parquet напрямую; PostgreSQL не является транспортом анализа.

## Зависимости

Go 1.27.2 (зафиксирован в go.mod; Go с `GOTOOLCHAIN=auto` может скачать toolchain),
Python 3.12, Docker Desktop с рабочим Linux engine или PostgreSQL 17, `psql`.
Команды ниже — PowerShell, из корня репозитория:

```powershell
go version
go mod download
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r tools/dataset/requirements.txt
go build ./...
```

Если `py` недоступен, используйте полный путь к установленному Python 3.12 для
создания `.venv`. В Codex на этой машине venv создан штатным bundled Python 3.12.14.
Runtime обработки/воспроизведения — Go; Python не входит в Worker/Master runtime.

## PostgreSQL

Создать локальный `.env` из примера и установить свой пароль. Примерный пароль
в `.env.example` предназначен только для замены, не для общего сервера.

```powershell
Copy-Item .env.example .env
# После редактирования .env:
docker compose up -d postgres
docker compose ps
docker compose exec -T postgres psql -U cluster_anomaly -d cluster_anomaly -v ON_ERROR_STOP=1 -1 -f /migrations/V1__core_schema.sql
$env:DATABASE_URL = 'postgresql://cluster_anomaly:YOUR_PASSWORD@localhost:5433/cluster_anomaly'
```

Compose читает `.env`; Python/Go не загружают `.env` автоматически. Экспортируйте
env самостоятельно. При special characters URL-encode пароль в DATABASE_URL.
Порт 5433 специально отделён от существующего PostgreSQL на 5432. Если изменены
POSTGRES_USER/POSTGRES_DB/POSTGRES_PORT, изменить команды соответственно.

V1 применяется **один раз к новой чистой БД**. При наличии старой schema project
не удалять её: выбрать новую отдельную БД. Альтернативно для уже подготовленной
новой native PostgreSQL базы:

```powershell
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -1 -f db/migrations/V1__core_schema.sql
```

Demo в обычном запуске не загружается. `docker compose down` останавливает сервис
и сохраняет volume. Команд уничтожения данных в этом workflow нет.

## Получение и подготовка Summit

Раздел описывает существующий исторический workflow Builder для трёх отдельных
файлов. В актуальном эксперименте НИР подготовка и скачивание не повторяются:
используется существующий `data/prepared/summit-D1-pilot/D1.parquet` и `cmd/nir`.

Источники: [официальный набор ORNL](https://doi.org/10.13139/OLCF/1861393),
[описание авторов](https://github.com/at-aaims/summit_power_and_thermal_data)
и используемая копия [ClusterWise](https://huggingface.co/datasets/MachaParfait/ClusterWise).
Требуются три существующих последовательных дневных файла `powtemp_10sec_mean`
одного месяца. Сохранить в `data/raw`; в командах ниже используются **локальные**
имена day1/day2/day3, не заявленные официальные filenames.

```powershell
.venv/Scripts/python.exe tools/dataset/inspect_dataset.py data/raw/day1.parquet data/raw/day2.parquet data/raw/day3.parquet --report data/raw/inspection.json
Copy-Item configs/feature-mapping.template.json configs/feature-mapping.local.json
# Заполнить mapping по реальной schema, включая отдельные полные списки CPU0/CPU1 cores.
.venv/Scripts/python.exe tools/dataset/inspect_dataset.py data/raw/day1.parquet data/raw/day2.parquet data/raw/day3.parquet --mapping configs/feature-mapping.local.json --report data/raw/inspection.json
.venv/Scripts/python.exe tools/dataset/build_dataset.py --d1 data/raw/day1.parquet --d2 data/raw/day2.parquet --d3 data/raw/day3.parquet --mapping configs/feature-mapping.local.json --output data/prepared --postgres "$env:DATABASE_URL"
```

Первый Inspector возвращает 2 до подтверждения mapping. Для naive timestamp
добавить `--timezone` с подтверждённым source timezone во все inspection/build
команды. Имена неизвестных CPU columns и часовой пояс не угадываются.

Без БД использовать `--no-postgres`. Для замены существующих outputs/изменённой
телеметрии — `--replace-dataset`. Повторный standalone import совпадающих данных:

```powershell
.venv/Scripts/python.exe tools/dataset/import_postgres.py --prepared data/prepared --postgres "$env:DATABASE_URL"
```

Результат: D1.parquet/D2.parquet/D3.parquet, manifest с source/prepared hashes,
schema/mapping, dates, topology, quality, missingness, masks и версиями.
16×18 topology выбирается детерминированно, с вложенными 4⊂8⊂16 конфигурациями.
CPU температуры — среднее finite non-null cores. Missing feature сохраняется NULL,
missing sample не генерируется. COPY загружает доступные F18 coordinates.

## Проверка базы и восстановление F18

```powershell
psql "$env:DATABASE_URL" -c 'select count(*) from project.node;'
psql "$env:DATABASE_URL" -c 'select count(*) from project.node_group;'
psql "$env:DATABASE_URL" -c 'select count(*) from project.metric_source;'
psql "$env:DATABASE_URL" -c 'select count(*) from project.telemetry;'
```

Для чистой БД после **успешного реального** import ожидаются 288 nodes, 17 groups
(SUMMIT + 16), 5184 metric_source. Число telemetry измеряется фактически с учётом
missing coordinates, а не объявляется равным rows×18 заранее.

История конкретного node (`$1` заменить фактическим id в psql):

```sql
select t.ts, ms.source_key, mt.code, t.value
from project.telemetry t
join project.metric_source ms on ms.id=t.metric_source_id
join project.metric_type mt on mt.id=ms.metric_type_id
join project.component c on c.id=ms.component_id
where c.node_id=1
order by t.ts, ms.source_key
limit 36;
```

Все 18 координат — `db/queries/f18.sql`. Применить параметризованный helper из
PowerShell (использовать реальные node_id и timestamp из БД):

```powershell
$f18Query = Get-Content db/queries/f18.sql -Raw
("PREPARE f18(integer,timestamptz) AS " + $f18Query + " EXECUTE f18(1,'2020-01-01T00:00:00Z');") | psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1
```

Timestamp в этом примере условный, не дата реально обработанного Summit.
Helper возвращает NULL для отсутствующих координат. Go counterpart:
`telemetry/repository.PostgresHistory.RecordAt` с массивами, NaN и availability mask.

## Replayer

```powershell
go run ./cmd/replayer --input data/prepared/D3.parquet --speed 100
go run ./cmd/replayer --input data/prepared/D3.parquet --speed 0 --output stdout
```

`--speed 1` — исходное pacing, `10`/`100` — ускорение, `0` — без намеренных задержек.
Scheduler использует исходные logical timestamps и абсолютную timeline, учитывая
время отправки. Порядок timestamp → group_id → hostname проверяется; файл не
сортируется и не рандомизируется в runtime. Все rows, включая invalid, отправляются.
Конец каждой пары timestamp/group — отдельное TimestampComplete с числом отправленных
и valid rows. Он не утверждает, что в группе присутствовали все 18 hosts.

По умолчанию slog пишет только summary в stderr. `--verbose` / `LOG_LEVEL=DEBUG`
включают records. `--output stdout` пишет NDJSON telemetry и timestamp_complete
в stdout, с JSON null вместо missing coordinates. Массив f18 следует порядку
feature_order в manifest. stdout adapter реализует порт отправителя; runtime
не привязан к stdout и готов к последующей замене adapter.

Env: DATABASE_URL, REPLAYER_INPUT, REPLAYER_SPEED, LOG_LEVEL. Явные flags имеют
приоритет. Ctrl+C отменяет чтение/pacing; повреждение Parquet, нарушение schema,
ошибки отправителя или порядка возвращают ненулевой exit code.

## Тесты

Компонентная физическая модель обучается на D1 и применяется к D2 через
`go run ./cmd/physical`. Восемь коэффициентов, остатки, MAE, наивный baseline,
устойчивость и явно заданный J описаны в
[отчёте реального расчёта](docs/real-component-physical-profile.md).
`--profile` загружает физический профиль без повторного обучения.

Быстрые unit checks:

```powershell
go test ./...
.venv/Scripts/python.exe -m pytest tools/dataset/tests -q
go vet ./...
```

Для полного небольшого fixture прогона нужна **явно указанная отдельная тестовая
PostgreSQL** и пользователь с CREATE DATABASE. Integration tests создают базы с
генерируемыми kr_f18_test_/kr_go_test_ именами, применяют migration к чистым базам,
проверяют COPY/repeat/reconstruction и удаляют только свои exact-name базы.
Caller DB и существующие пользовательские schemas не сбрасываются.

```powershell
$env:TEST_DATABASE_URL = 'postgresql://TEST_USER:TEST_PASSWORD@localhost:5433/postgres'
go build -o .tools/replayer.exe ./cmd/replayer
$env:REPLAYER_BINARY = (Resolve-Path .tools/replayer.exe).Path
go test ./...
.venv/Scripts/python.exe -m pytest -q
go build ./...
go vet ./...
```

Без TEST_DATABASE_URL реальные DB tests выводят SKIP, без REPLAYER_BINARY
cross-language test — SKIP. Пропущенная проверка не считается PASS.
Фикстуры явно синтетические и создаются только в test tempdir; реальный Summit
build/import и размеры/coverage остаются отдельной обязательной проверкой.
