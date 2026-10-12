# Архитектурный контракт начального этапа КР

Modular monolith / multi-binary application, адаптированный из
[WorkNet](https://github.com/butorovv/worknet-backend).
В WorkNet `cmd/api` вызывает composition root `internal/app`, который собирает
domain/usecase/repository и технические adapters. Здесь тот же принцип применяется
к телеметрии кластера, без переноса auth/HTTP/Redis и предметных сущностей WorkNet.

- `cmd/replayer`: только запуск приложения и exit code.
- `internal/app`: конфигурация, slog, wiring, жизненный цикл и сигналы отмены.
- `internal/modules/telemetry/domain`: TelemetryRecord, топология; без PostgreSQL,
  Parquet, Kafka или HTTP. F18 имеет фиксированный порядок 2+2+6+2+6.
- `internal/modules/telemetry/usecase`: порт чтения исторического состояния.
- `internal/modules/telemetry/repository`: pgx adapter канонической схемы.
- `internal/replayer`: потоковое чтение prepared Parquet, pacing, порт отправителя,
  завершение пары timestamp/group. Анализ отсутствует.
- `internal/platform`: config, logger, PostgreSQL pool.
- `tools/dataset`: Python 3.12 offline inspection, подготовка, COPY import.

Поток: raw Parquet → Builder → prepared D1/D2/D3 и PostgreSQL.
Replayer читает prepared Parquet напрямую. PostgreSQL не участвует в вычислительном
транспорте. Worker, Master, detection, grouping, monitoring, GUI и Kafka не реализованы.

Канонический V1: `db/source.json`. Все PK/FK/CHECK/UNIQUE, функции, триггеры,
комментарии и связи сохранены. Пять строк metric_type — обязательный справочник,
остальные исходные INSERT — только `db/demo`.

В prepared timestamps явно переводятся в UTC, сохраняется исходный момент.
Для naive timestamps требуется явный часовой пояс через `--timezone`;
допущение и степень подтверждения сохраняются отдельно в manifest.
Требуется 10-секундная сетка и три последовательных UTC дня одного месяца.
CPU-core mapping задаётся явно после inspection. Builder никогда не выбирает
между неоднозначными колонками. Пропуск координаты — NULL в Parquet, отсутствие
measurement в PostgreSQL и снятый бит маски. Пропуск целого sample не восполняется:
его число отражается в manifest; TimestampComplete подтверждает только отправленные
записи группы, а не полноту 18 хостов.

Память Builder ограничена batch (8192 строк) и 8640-битными картами каждого host
для проверки дубликатов. Проекция выбранных 288 host сортируется через временную
SQLite на диске. Требуется место для raw, prepared и временной сортировки одного дня.
COPY выполняется пакетами через временную таблицу внутри одной транзакции;
в D1 pilot каждое ограниченное окно импортируется отдельной транзакцией,
а прогресс сохраняется атомарно между окнами.
advisory lock защищает конкурирующие SUMMIT imports. Недостаток диска/ошибка
подготовки/импорта не считается успешным завершением.

Повторный import пропускает совпадающие natural keys и отклоняет изменённые значения.
`--replace-dataset` удаляет только telemetry выбранных 18 sources/node и UTC интервала
D1..D3 включительно, затем заново загружает их в той же транзакции. Узлы, группы,
источники вне выборки, события и сервисные сущности не удаляются. Importer не принимает
чужую или демонстрационную топологию с совпадающим именем SUMMIT.
