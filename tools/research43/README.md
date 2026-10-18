# Исследование №4.3: архив и воспроизведение после интеграции

H1/H2 — исследовательские каналы. Действующий локальный detector — B1 в
`internal/local` / `cmd/local`; H2 туда не подключён. Групповой detector,
GroupEvent, Kafka, Master/Worker, API и GUI этой интеграцией не реализованы.

## История и единый источник №4.1

Первоначальные отчёты [docs/research-4.3](../../docs/research-4.3/) и 25 PNG
сохранены из `3db631177bc5080d211ee512c07790a4325c98a6`. Исследовательская линия:
`aa509f61a75385e638ed0de76fe561a199aa570e` (power-asymmetry),
`d4f40c832f4e4a40b233c14525da4d60e9940699` (H1/H2),
`3db631177bc5080d211ee512c07790a4325c98a6` (сравнение и отрицательный итог H2).
Первый commit уже входит в историю второй ветки; отдельный cherry-pick не нужен.

№4.1/4.2 вошли в main через PR №5/6; B1 — через PR №7
(`ecd95ab33c65ca977bd91850c4fe755d4e988f1d`). Сведения старых отчётов о
неслитых ветках описывают 14.10.2026. Они не являются текущим статусом Git.
№4.3 подготовлено к включению через `integration/research-4-3`; до слияния
интеграционного PR его ancestry ещё не входит в main.

Оригинальные `tools/diagnostics/` — единственный источник функций №4.1.
Копия vendor/research41 удалена после проверки идентичности четырёх Git blobs,
тестов и численной сверки; Python использует квалифицированный импорт
`tools.diagnostics.diagnostic_stats`, защищённый от старого short-name module cache.

| Историческая копия (из 79a144125ba5a05d21a999516e210ba6e604e6e2) | SHA-256 canonical Git bytes |
|---|---|
| diagnostic_stats.py | 325bed2c7f3f031751173412040aba19f97b74a03b56ff03d25e7348ed53e141 |
| analyze_d2.py | 33295c108daf2cccca79e61d469be3ecf15732344ff246e77c13dd31a23ca35b |
| requirements.txt | 4b8f2d09b375a514f90bb951bf8386e5cbb3466c870bce7222e83bb7c86deff1 |
| export/main.go | 31dfe33052cf1813ef83fc5813cdad68b827cf822aa430c7de90c3ccaff9bd21 |

Историческое воспроизведение старого дерева доступно по оригинальным SHA через
отдельный checkout. На текущем дереве команды vendor заменяются
`go run ./tools/diagnostics/export` и `python tools/diagnostics/analyze_d2.py`.
Полные экспорты/обучение B2 заново для обычной регрессии не нужны.

## Неизменные входы

Требуются prepared Parquet/manifest и прежние statistical/isolation/physical/
calibration profiles, `results/d2-diagnostics-v1`, `results/context-v1`,
`results/research43-v4`, `results/research43-stage2-v1`.
Большие файлы не входят в Git; отсутствующие входы означают невозможность
реальной проверки, а не PASS. Финальный v4 не подменять остановленным v1
или промежуточными v2/v3. Не менять модели и не калибровать на D2.
Схема availability №4.1 — boolean 1, №4.2 — F18 mask 262143;
это проверенное различие форматов, а не расхождение леса.

Все научные вычисления этой линии ограничены D1/D2 18.01.2022, 288×2880
состояний на окно. D3 не используется этими скриптами; он уже просматривался
другим статистическим этапом и не является pristine holdout всего проекта.
Группы hostname — логическое разбиение, не доказанная физическая топология.

## Безопасная обычная проверка

Из корня репозитория, с прежним окружением из requirements №4.1 и локального
diagnostics cache; зависимости не обновлять:

```powershell
$env:OPENBLAS_NUM_THREADS='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -p no:cacheprovider tools/dataset/tests tools/diagnostics/tests tools/context/tests tools/research43/tests
python tools/context/check_reproduction.py
python tools/research43/check_reproduction.py
go test ./...
go build ./...
go vet ./...
$env:LOCAL_B1_REAL='1'
go test -count=1 -v ./internal/local -run TestRealB1D2MatchesResearch
Remove-Item Env:LOCAL_B1_REAL
```

`check_reproduction.py` только читает артефакты: повторяет audits I/II,
проверяет H1 absolute/B1, D1 thresholds и все определённые H2 scores,
14341/6012/5895/11907 signals, observed pairs и все 1999×8×2 сохранённых
topology controls, statistical comparisons и SHA до/после. Это воспроизведение
прежнего контроля, не новый подбор параметров. Не запускать Python с `-O`.

Audits по умолчанию выводят JSON в stdout; старый audit.json не перезаписывается.
Для нового файла допустим `--audit-output <NEW_EXTERNAL_JSON>` (создание exclusive).
Markdown-протоколы №4.3 закреплены LF через .gitattributes: их исторические
SHA были вычислены по LF; смена CRLF при Windows checkout нарушала проверку.

## Повторный расчёт и генерация отчётов

Только при технической необходимости. Каждый output/report/figures каталог
должен быть новым. Старые результаты не удаляются:

```powershell
python tools/research43/analyze.py --output <NEW_STAGE1>
python tools/research43/audit.py --output <NEW_STAGE1> --audit-output <NEW_STAGE1>/audit.json
python tools/research43/compare.py --stage1 <NEW_STAGE1> --output <NEW_STAGE2>
python tools/research43/audit_compare.py --output <NEW_STAGE2> --audit-output <NEW_STAGE2>/audit.json
python tools/research43/write_report.py --output <STAGE1> --report-dir <NEW_REPORT1>
python tools/research43/write_comparison.py --output <STAGE2> --report-dir <NEW_REPORT2>
```

Stage I figures по умолчанию пишутся в NEW_STAGE1/figures; явный `--figures`
также должен быть новым. Оригинальные docs/research-4.3 и их подпапки защищены.
Генераторы требуют явный новый report-dir, используют исторический текстовый
шаблон с заметным предупреждением о дате Git-сведений и не переписывают original
reports. Ссылки шаблона на протоколы/Stage I plots относятся к исходному
docs/research-4.3; при переносе отчётного набора приложите их из исходного
архива или нового расчёта. Stage II графики создаются внутри нового report-dir.
При отсутствии platform.json текущая среда сохраняется только в новом report-dir,
не записывается задним числом в исторический эксперимент.

`forest_benchmark` сохранён и собирается общим go build/vet. Полный benchmark
(прогрев + пять прогонов A0/B2) не требуется обычной регрессии и пишет только
новый файл `-output`; он не обучает лес. Производительность старого эксперимента
не выдаётся за новое измерение.

## Сохраняемые выводы

H1 сохраняет абсолютный IF score, отдельный absolute flag и context B1
без OR и переобучения. H2 — фиксированное 60 s приращение GPU/CPU/PSU,
D1 median/MAD/floor и pooled Q99.5 по направлениям; первые 6 ticks undefined.
Не смешивать flags=false с valid=false в исследовательских масках.
Missing/cadence/time boundaries проверяются synthetic unit fixtures.

H2 не рекомендован основным каналом: доминирует PSU, есть lag dependence
и положительные echoes через 60 s после отрицательных изменений.
Независимых меток аппаратных неисправностей нет. Отрицательные результаты,
risk sets, pair/topology/equal-budget сравнения и реальные графики сохранены.
H3 не реализована. Интеграция исходников не завершает НИР/КР и не меняет B1.
