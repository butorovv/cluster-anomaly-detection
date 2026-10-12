# Канонический PostgreSQL V1

Источник: [seminar02/migrations/V1__init.sql](https://github.com/butorovv/kdbd-cluster-monitoring/blob/901091cf143942dbf8c883d233d390787e3c51d1/seminar02/migrations/V1__init.sql).
Commit, исходный SHA256 и точное преобразование записаны в `source.json`.
DDL перенесён без изменения семантики или текста (кроме заголовка происхождения
и нормализации переносов строк). Пять metric_type INSERT оставлены в core как
обязательный справочник. Все учебные сущности и измерения — в `demo/`.

Требуется чистая новая база; V1 применяется один раз, транзакционно:

```powershell
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -1 -f db/migrations/V1__core_schema.sql
```

Для Compose миграции доступны как readonly `/migrations`:

```powershell
docker compose exec -T postgres psql -U cluster_anomaly -d cluster_anomaly -v ON_ERROR_STOP=1 -1 -f /migrations/V1__core_schema.sql
```

Здесь нет automatic reset базы или удаления volumes. Повторное применение V1
к существующей схеме завершится ошибкой и откатом. Повторный import телеметрии
поддерживается отдельно загрузчиком, без повторного DDL.

Optional demo применяется **только к отдельной учебной базе** после core:

```powershell
psql "$env:DEMO_DATABASE_URL" -v ON_ERROR_STOP=1 -1 -f db/demo/V1__demo_data.sql
```

Данные Summit нельзя загружать в demo-базу: importer отклоняет совпадающие
не принадлежащие ему SUMMIT/group/host записи. Рабочая цепочка:
node_group → node → component → metric_source → telemetry.

`queries/f18.sql` принимает `$1` = node_id, `$2` = logical timestamptz. Возвращает
18 nullable coordinates, hostname, group_id и node_index. Названия source_key
совпадают с prepared F18 fields; связь с metric_type и component остаётся канонической.
Go `PostgresHistory.RecordAt` восстанавливает ту же структуру с NaN для NULL и маской.
Числа валидных CPU cores доступны в Parquet, но в каноническую telemetry не добавляются.

Prepared invalid row не отбрасывается целиком: в БД загружаются его доступные
координаты. NULL/NaN/Infinity не загружаются как measurement. Если отсутствуют все
18 измерений, БД не хранит сам факт sample; prepared Parquet остаётся источником
полной availability metadata.
