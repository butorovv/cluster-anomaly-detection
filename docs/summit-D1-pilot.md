# Summit ClusterWise D1 pilot

Источник: [MachaParfait/ClusterWise](https://huggingface.co/datasets/MachaParfait/ClusterWise),
`202201/20220118.parquet`. SHA256:
`7b6bcb905616865312fdd620d0f3aac9c82b1fcb23dfc1f547d068233cd18934`.

Это предварительный D1 pilot: выбор 16×18 ещё не подтверждён D2/D3.
V1 и long-format `project.telemetry` сохранены.

## Время и F18

Исходный `timestamp[ms]` не содержит timezone. По явному решению пользователя
время суток сохраняется, а timestamp интерпретируется как UTC. Manifest:
`source_timezone: unknown`, `assumed_timezone: UTC`, `timezone_verified: false`.
То же правило применяется к последующим D2/D3 через `--timezone UTC`.
Для SQL-проверок использовать `SET TIME ZONE 'UTC'`: сессия PostgreSQL может
отображать тот же TIMESTAMPTZ-момент в своём часовом поясе. Это не меняет stored values.
Для проверки другой гипотезы подготовить данные в новой папке, сверить их и
выполнить явную замену соответствующего импортируемого временного окна
через `import_postgres.py --replace-dataset --start ... --end ...`.
При сдвиге timezone необходимо также согласовать очистку старого временного
диапазона: автоматического удаления истории в pilot runner нет.

`configs/feature-mapping.clusterwise.json` явно сопоставляет PSU, CPU,
GPU power (p0 GPU0..2 → GPU0..2; p1 GPU0..2 → GPU3..5) и GPU core temperature.
CPU mean уже вычислены источником (`p0_temp_mean`, `p1_temp_mean`), отдельных
core columns нет. Они сохраняются без повторного усреднения. Для такого mapping
`cpu*_valid_cores=-1` означает неизвестное количество cores, включая missing mean.
Обычный mapping со списком cores по-прежнему вычисляет среднее и фактический count.
Availability mask определяется только finite F18 values; missing сохраняются NULL.

В реальном файле есть hostname групп выше 24, вплоть до h50. Python и Go
проверяют код `[a-h][0-9]{1,2}n[0-9]{1,2}` и позицию 1..18 без выдуманной
верхней физической границы группы. Полные группы выбираются по качеству D1.

## Воспроизводимые команды

Из корня проекта, используя существующий venv и PostgreSQL на 127.0.0.1:55432:

```powershell
.venv/Scripts/python.exe tools/dataset/download_day.py
.venv/Scripts/python.exe tools/dataset/inspect_dataset.py data/raw/20220118.parquet --timezone UTC --mapping configs/feature-mapping.clusterwise.json --grid-day --report data/raw/inspection-D1.json
.venv/Scripts/python.exe tools/dataset/build_dataset.py --pilot --d1 data/raw/20220118.parquet --mapping configs/feature-mapping.clusterwise.json --timezone UTC --output data/prepared/summit-D1-pilot --no-postgres
$env:DATABASE_URL='postgresql://kr_test@127.0.0.1:55432/cluster_anomaly_dev'
.venv/Scripts/python.exe tools/dataset/import_pilot.py --prepared data/prepared/summit-D1-pilot --until-minutes 10
.venv/Scripts/python.exe tools/dataset/import_pilot.py --prepared data/prepared/summit-D1-pilot --until-minutes 60
.venv/Scripts/python.exe tools/dataset/import_pilot.py --prepared data/prepared/summit-D1-pilot
.venv/Scripts/python.exe tools/dataset/verify_pilot.py --prepared data/prepared/summit-D1-pilot
```

Download пишет единственный `.part`, проверяет Range offset, размер и SHA256,
публикует файл переименованием. Ctrl+C сохраняет partial; повтор той же команды
докачивает. Свободное место проверяется перед каждым блоком 8 МиБ, прогресс
печатается каждые 256 МиБ. Готовый raw не перезаписывается.

Inspector `--grid-day` проверяет все колонки пакетно и использует точные битовые
карты ключей одного дня вместо большой SQLite-копии. Builder использует существующий
пакетный projection и SQLite sort только для выбранных 288 hosts; временный sort
удаляется после подготовки. Нет копии всего raw или целого дня в RAM.

Runner допускает только `cluster_anomaly_dev`; готовый D1 проверяется по SHA256.
Каждое окно COPY коммитится независимо. `import-progress.json` атомарно сохраняет
следующий timestamp, coverage, измерения, время, размеры heap/index/DB/WAL,
LSN и свободное место. После первых 10 минут проверяются counts и повторный
импорт (inserted=0), после часа — counts и оценка дня. Дальше окна по 10 минут,
рядом с дисковым резервом — по 2 минуты. Повтор последнего окна после сбоя
между commit и checkpoint сверяет значения и не создаёт дубликаты.

Резерв **5 ГиБ** консервативнее требуемых 5 ГБ. Дополнительно удерживается
минимум 256 МиБ на текущий COPY/INSERT, WAL и rollback. Проверки идут перед
окнами и каждым batch. Пользовательские файлы и загруженная история не удаляются.
Чтобы остановить после текущего окна, создать в prepared папке файл
`STOP_IMPORT`; для возобновления убрать только этот собственный маркер и повторить
команду. Ctrl+C откатывает текущее окно, предыдущие сохраняются.

`verify_pilot.py` запускает настоящий Go executable с `--speed 0 --output stdout`,
сравнивает каждую запись с Parquet потоково, включая timestamps/F18/mask/validity,
и проверяет каждое TimestampComplete. NDJSON целиком на диск не сохраняется.
Канонический SQL F18 сравнивается для шести реальных узлов.
Фактические результаты находятся в локальном raw inspection и prepared
`manifest.json`, `import-progress.json`, `real-verification.json`; они исключены из Git.
