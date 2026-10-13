# Исследовательская диагностика D2

Эти инструменты читают фиксированные модели и данные. Они не входят в основной
детектор, не обучают модели и не подбирают пороги. Итоговый отчёт:
[docs/d2-anomaly-diagnostics.md](../../docs/d2-anomaly-diagnostics.md).

Запускать из корня репозитория. Нужны существующие локальные файлы этапов A–D,
подготовленный `data/prepared/summit-D1-pilot/D1.parquet` и для проверки аннотаций
`data/raw/20220118.parquet`. Python-пакеты указаны в `requirements.txt`; используйте
отдельное локальное окружение. Go-зависимости проекта не меняются.

```powershell
$env:OPENBLAS_NUM_THREADS='1'
go run ./tools/diagnostics/export -output results/d2-diagnostics-v1
python tools/diagnostics/analyze_d2.py --repeats 1999 --seed 42
python tools/diagnostics/inspect_raw_labels.py --output results/d2-diagnostics-v1/raw-annotations-v2.json
python tools/diagnostics/audit_d2.py
python tools/diagnostics/write_report.py
python -m pytest tools/diagnostics/tests -q -p no:cacheprovider
```

Экспорт и сырые аннотации создают новые файлы эксклюзивно и не перезаписывают
старые. Для повторного независимого экспорта укажите новый `-output` и затем
тот же путь через Python `--export`; `write_report.py` намеренно читает
зафиксированный каталог `results/d2-diagnostics-v1` конкретного исследования.
Анализ/аудит можно повторять на неизменном экспорте: заменяются только производные
исследовательские JSON, NPZ, CSV, графики и отчёт. Исходные файлы остаются read-only.

`states.bin` — 176 байт на состояние, little-endian: int64 Unix microseconds,
uint32 host index, uint32 available, 18 float64 F18, float64 IF score, float64 D².
`metadata.json` сохраняет проверенные хеши входов, порядок хостов/признаков,
аудит окна и исходные профили. Для произвольных неполных данных анализ прекращается:
это исследование полного D2, не универсальная обработка пропусков.

Все большие результаты остаются в игнорируемом `results/`. В Git входят только
скрипты, тесты, Markdown и пять необходимых рисунков. Данные, профили, промежуточные
массивы и установленное Python-окружение не публикуются.

Случайные операции: основной общий исследовательский RNG PCG64 seed=42 (20
случайных PR-ранжирований, 499 разбиений групп, выбор тихого интервала, scatter),
отдельные RNG для 1999 циклических контролей seed=42 и 499 контролей seed=43;
независимая проверка IF использует seed=123. Порядок потребления RNG фиксирован
кодом. Для идентичного воспроизведения используются закреплённые версии NumPy.

Сырые метки сопоставляются только по timestamp/hostname под временным допущением
манифеста. `label=1` и XID31 не объявляются подтверждённым аппаратным отказом.
