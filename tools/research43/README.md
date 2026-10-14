# Исследование №4.3: только этапы 0/I

Код экспериментальный. Не используется основной системой; кандидаты H1–H3
не реализованы. [План](../../docs/research-4.3/STAGE-PLAN.md),
[протокол до расчёта](../../docs/research-4.3/01-analysis-protocol.md).

## Входы и восстановление из чистого checkout

Нужны неизменные реальные prepared Parquet/manifest и основные сохранённые
профили statistical/isolation/physical/calibration из `results/`. Они сохраняются
отдельно от Git. Имена и SHA приведены в отчёте 00. Модели нельзя заменить
переобученными и молча назвать тем же baseline. Данные содержат полный день;
читатели ограничивают научные вычисления D1/D2. SHA полного Parquet не анализирует D3.

Если производных артефактов ещё нет, из **чистого рабочего каталога**:

```powershell
go run ./tools/research43/vendor/research41/export -output results/d2-diagnostics-v1
python tools/research43/vendor/research41/analyze_d2.py --repeats 1999 --seed 42 --figures .cache/research41-figures
python tools/context/baseline.py
go run ./tools/context/export -output-dir results/context-v1
python tools/context/analyze.py --figures .cache/research42-figures
```

Это восстановление экспортов и контроля, включая экспериментальное обучение
B2 и seed43/44 на D1. В текущем этапе повторены арифметика хешированных экспортов
и независимые 1024 состояния на каждую из шести моделей и каждого окна,
а также новый полный Go-export A0/Mahalanobis D2. Это явно разные проверки.
Существующие артефакты предыдущих исследований не удалять и не перезаписывать.
При наличии экспортов команды восстановления пропустить.

```powershell
$env:OPENBLAS_NUM_THREADS='1'
python tools/research43/analyze.py --output results/research43-replay
python tools/research43/audit.py --output results/research43-replay
python tools/research43/write_report.py --output results/research43-replay
python -m pytest -q -p no:cacheprovider tools/context/tests tools/research43/tests
go test ./...
go build ./...
go vet ./...
go build -o .cache/research41-export.exe ./tools/research43/vendor/research41/export
```

`--output` должен быть новым каталогом; повторный расчёт — с новым именем.
Окончательные артефакты проведённого расчёта — `results/research43-v4`;
v1 — остановка на различии схем availability; v2/v3 — промежуточные,
до исправления граничного исключения контролей. Они не удалены и не заменяют v4.
Для этой машины Python:
`C:/Users/Георгий/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`;
`PYTHONPATH` = `.cache/diagnostics-python;.venv/Lib/site-packages`.
Go: `.cache/gomod/golang.org/toolchain@v0.0.1-go1.27.2.windows-amd64/bin/go.exe`,
`GOTOOLCHAIN=local`, `GOCACHE=$PWD/.cache/gobuild`, `GOMODCACHE=$PWD/.cache/gomod`.
Новые зависимости не установлены. `go ./...` пропускает vendor: exporter
проверяется отдельным build/run. Малые fixtures проверяют только программную логику.

## Замороженная зависимость №4.1

Четыре файла скопированы **побайтно** через `git show` из
`79a144125ba5a05d21a999516e210ba6e604e6e2:tools/diagnostics/`.
Git ancestry веток не объединена. Исторические отчёты сохранены в прежних ветках.
В будущей согласованной интеграции 4.1 → 4.2 → 4.3 копию можно заменить
единым tracked модулем с теми же численными тестами.

| Файл в vendor/research41 | SHA-256 |
| --- | --- |
| diagnostic_stats.py | 325bed2c7f3f031751173412040aba19f97b74a03b56ff03d25e7348ed53e141 |
| analyze_d2.py | 33295c108daf2cccca79e61d469be3ecf15732344ff246e77c13dd31a23ca35b |
| requirements.txt | 4b8f2d09b375a514f90bb951bf8386e5cbb3466c870bce7222e83bb7c86deff1 |
| export/main.go | 31dfe33052cf1813ef83fc5813cdad68b827cf822aa430c7de90c3ccaff9bd21 |

Исследование №4.1 хранит availability как uint32 boolean=1, №4.2 как
полную F18 bitmask=262143. Audit сравнивает смысл доступности, а остальные
поля и A0 score/D²/F18 — побайтно/по значениям. Разница схемы не расхождение модели.

## Артефакты

`baseline.json`: SHA, пороги, численная сверка и контрольные счётчики;
`events.json`: все реальные события, параметры контроля, score/физика и окна;
`summary.json`: распределения, bootstrap по host/hour/half-hour, таблицы;
`audit.json`: независимые временные счётчики. Всё это в ignored results.
В Git — исходники, тесты, протокол, Markdown и PNG. Каждый PNG создаётся
из реальной телеметрии. Результаты I не являются независимой оценкой отказов.
