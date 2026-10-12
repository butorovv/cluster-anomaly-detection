# Offline Dataset Inspector / Builder

Python используется только offline. Зависимости зафиксированы в `requirements.txt`.
Все команды ниже выполняются из корня `cluster-anomaly-detection`.

Для обычного build должны существовать **все три** файла в `data/raw/`.
Однодневный реальный pilot, безопасная докачка и постепенный COPY описаны в
[Summit D1 pilot](../../docs/summit-D1-pilot.md). Он использует `--pilot` и
предварительный выбор групп только по D1.
Источники данных перечислены в [README проекта](../../README.md#получение-и-подготовка-summit).
`day1.parquet`/`day2.parquet`/`day3.parquet`
ниже — локальные имена после получения; официальные имена ещё не подтверждены.

```powershell
.venv/Scripts/python.exe tools/dataset/inspect_dataset.py data/raw/day1.parquet data/raw/day2.parquet data/raw/day3.parquet --report data/raw/inspection.json
```

Если timestamp naive, повторить с явно выбранным `--timezone`.
UTC не предполагается автоматически; допущение фиксируется отдельно от
подтверждённого timezone в manifest. Inspector печатает
schema, все колонки, физические/logical types, количество строк и hosts, диапазон
времени, интервалы, дубликаты, пропуски и кандидаты CPU0/CPU1 core колонок.
Keys интервальных статистик — секунды между соседними уникальными states каждого host.
Для произвольных интервалов Inspector использует дисковую SQLite, а не весь набор в RAM.

Первый inspection возвращает exit code 2: schema показана, mapping не подтверждён.
Это диагностический этап, а не успешное подтверждение F18. После просмотра реальной
схемы скопировать `configs/feature-mapping.template.json` в
`configs/feature-mapping.local.json`, заполнить точные имена и **полные отдельные
списки CPU0 и CPU1 core temperature columns**, либо строкой указать явный готовый
CPU mean column источника. Placeholder-шаблон намеренно невалиден;
никакого mapping неизвестных CPU columns он не утверждает.

```powershell
Copy-Item configs/feature-mapping.template.json configs/feature-mapping.local.json
.venv/Scripts/python.exe tools/dataset/inspect_dataset.py data/raw/day1.parquet data/raw/day2.parquet data/raw/day3.parquet --mapping configs/feature-mapping.local.json --report data/raw/inspection.json
```

После ручного заполнения mapping второй inspection должен вернуть 0. При ином
имени timestamp/hostname передать `--timestamp-column` / `--hostname-column`.
Для Builder эти имена записаны в mapping. Числовые epoch или строки не угадываются
как timestamps. Raw schema трёх файлов должна совпадать по именам/types/nullability.

```powershell
.venv/Scripts/python.exe tools/dataset/build_dataset.py --d1 data/raw/day1.parquet --d2 data/raw/day2.parquet --d3 data/raw/day3.parquet --mapping configs/feature-mapping.local.json --output data/prepared --postgres "$env:DATABASE_URL"
```

Без PostgreSQL заменить `--postgres ...` на `--no-postgres`. Для naive timestamps
добавить то же явное `--timezone`. Дни трактуются после нормализации в UTC:
три разных последовательных дня в одном месяце; корректная 10-секундная сетка.
Если исходные локальные сутки пересекают границу UTC-дня, Builder остановится,
а не переразобьёт данные незаметно. Дубликаты (host,time) запрещены во всём raw,
включая узлы вне выбранных групп. Alias-hostnames одной структурной позиции делают
группу неоднозначной, и она не выбирается.

Отбор: по 18 уникальных структурных позиций 1..18 во всех трёх днях, затем максимум
числа наблюдаемых states, минимум доли missing F18, lexical group_id. Одного отсутствующего
sample недостаточно для исключения группы. Manifest содержит quality для всех
пригодных групп и вложенные первые 4/8/16 групп. Отсутствующие samples не генерируются.

F18 порядок: 2 PSU power, 2 CPU power, 6 GPU power, 2 CPU mean temp, 6 GPU core temp.
CPU mean = сумма finite non-null cores / их число; все cores missing → NULL.
При mapping готового mean строкой значение сохраняется напрямую, а core count
равен -1 (неизвестно), поскольку источник не содержит core availability.
Сохраняются cpu0_valid_cores/cpu1_valid_cores, is_valid и 18-битная availability_mask.
is_valid означает наличие всех 18 F18, частичный CPU mean допускается.
NaN/Infinity переводятся в NULL, физические границы и anomaly labels не применяются.

Builder делает quality pass всех raw, затем projection pass только выбранных
288 hosts, сортирует на диске и публикует D1/D2/D3 + manifest. Manifest публикуется
последним как completion marker; при прерванной замене его отсутствие означает
незавершённую подготовку. Существующий output требует `--replace-dataset`.
SHA256 считаются для raw и prepared. `build_timestamp` меняется при повторении;
выбор, prepared bytes и статистики детерминированы для одинаковых inputs/mapping/version.

Если PostgreSQL import завершился ошибкой, prepared уже сохранены, но build вернёт
ненулевой код; import в manifest не считается completed. Исправить причину и выполнить:

```powershell
.venv/Scripts/python.exe tools/dataset/import_postgres.py --prepared data/prepared --postgres "$env:DATABASE_URL"
```

Повторный COPY-import совпадающих значений возвращает inserted_measurements=0.
При отличающихся значениях нужен явный `--replace-dataset`. Замена ограничена
sources выбранных hosts и трёх дней; выполняется в одной транзакции. Никакого
INSERT на отдельное measurement или промежуточного SELECT для анализа нет.
Standalone import выводит результат в stdout, но не изменяет manifest.

Тесты создают исключительно синтетические маленькие Parquet в pytest tempdir.
Они не заполняют `data/raw`/`data/prepared` и не подтверждают обработку Summit.
