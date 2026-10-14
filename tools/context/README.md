# Исследование №4.2

Код исключительно экспериментальный: не используется `cmd/*`, не меняет
основные профили или алгоритм РПЗ. Входы — реальные подготовленные Summit F18.
Протокол до расчётов: [context-experiment-protocol.md](../../docs/context-experiment-protocol.md).

Зависимость №4.1 включена в `main` через PR №5 (merge `d181d80`).
Импорты и команды воспроизведения используют оригинальные отслеживаемые
модули `tools/diagnostics` из коммита `79a1441`. Отдельный снимок зависимости
больше не требуется. Научные результаты и исходные формулы не изменены.

Нужны прежние неизменные файлы в `results/` и prepared Parquet/manifest.
Если экспорт №4.1 отсутствует, его воспроизводят из tracked исходников (новые файлы,
не перезаписывать старые), затем запускают прежний анализ для shift_controls:

```powershell
go run ./tools/diagnostics/export -output results/d2-diagnostics-v1
python tools/diagnostics/analyze_d2.py --repeats 1999 --seed 42 --figures .cache/research41-figures
```

NumPy 2.3.5, matplotlib 3.10.8, PyArrow 26.0.0, pytest 9.1.1 — существующее
исследовательское окружение №4.1. Go 1.27.2, новых Go-зависимостей нет.

```powershell
$env:OPENBLAS_NUM_THREADS='1'
python tools/context/baseline.py
go run ./tools/context/export -output-dir results/context-v1
python tools/context/analyze.py
python tools/context/audit.py
python tools/context/benchmark.py
python tools/context/write_report.py
python -m pytest -q -p no:cacheprovider tools/context/tests
go test ./...
go build ./...
go vet ./...
```

Exporter эксклюзивно создаёт экспериментальные файлы; повторный запуск требует
нового `-output-dir`. Анализ/аудит принимают фиксированный каталог результатов
исследования; не запускайте их на другом эксперименте без изменения путей/проверок.
`write_report.py` читает только `results/context-v1` и обновляет производный отчёт.
Для повторения полного конкретного эксперимента удалять исходные результаты
не требуется: используйте отдельную копию рабочего каталога с теми же входами.

В Windows sandbox launcher Go может пытаться проверить уже скачанный toolchain
через сеть. Для этой машины использован локальный кеш:

```powershell
$env:GOTOOLCHAIN='local'
$env:GOCACHE="$PWD/.cache/gobuild"
$env:GOMODCACHE="$PWD/.cache/gomod"
$goContext = "$PWD/.cache/gomod/golang.org/toolchain@v0.0.1-go1.27.2.windows-amd64/bin/go.exe"
& $goContext test ./...
```

Python этой машины: bundled runtime; `PYTHONPATH` включает существующие
`.cache/diagnostics-python` и `.venv/Lib/site-packages`. Тестовые fixtures для
арифметики не являются новым экспериментальным датасетом или разметкой отказов.

Binary layout216 байт little-endian: int64 unix_us, uint32 host index,
uint32 **F18 availability mask**,18 float64 raw F18,6 float64 score
(`a0-42,b2-42,a0-43,b2-43,a0-44,b2-44`),float64 D². Полная маска262143.
Каждое окно829440 строк. Timestamp/host порядок проверяется до reshape.
`metadata.json` связывает source/F18/медианы/леса/времена и SHA256 входов до/после.

Все binary, модели, пороги, per-event результаты и перестановочные массивы
остаются в ignored `results/`. В Git — код, тесты, протокол, Markdown-таблицы
и четыре научных графика. D3 не используется в статистике, fit или scoring;
проверка SHA256 полного входного файла не является анализом D3.
