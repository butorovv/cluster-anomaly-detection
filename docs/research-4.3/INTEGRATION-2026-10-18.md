# Интеграция исследования №4.3 — 18.10.2026

## Исходная Git-проверка

Рабочее дерево перед началом было чистым. Выполнены status, fetch origin --prune,
branch -a, log --all --oneline --decorate -30, branch -r --no-merged origin/main,
merge-base, log диапазонов, diff и cherry. Удалённый main:
`ecd95ab33c65ca977bd91850c4fe755d4e988f1d`. GitHub PR №7: merged=true,
merge commit тот же, время 18.10.2026 08:30:15 UTC. PR №1–7 видны merge-коммитами
в ancestry main. Устаревший локальный main `d181d80…` не использован как база
и не изменялся.

Только две source-ветки имеют собственные коммиты вне исходного main:

| Ветка | HEAD | Собственных коммитов вне исходного main |
|---|---|---:|
| research/power-asymmetry-4-3 | aa509f61a75385e638ed0de76fe561a199aa570e | 1 |
| research/h1-h2-comparison-4-3 | 3db631177bc5080d211ee512c07790a4325c98a6 | 3 |

Общий предок main и H1/H2: `98aab5865a9ee8d0d59c8fe51954047abab32ef8`.
`git cherry origin/main research/h1-h2-comparison-4-3` показывает три новых patch:
`aa509f6`, `d4f40c8`, `3db6311`. Power-asymmetry — предок H1/H2; отдельный
merge/cherry-pick дал бы дублирование. Неожиданных source-веток не обнаружено.
[Реестр исходных локальных/удалённых refs](BRANCH-REGISTER.md) различает ancestry
и tree differences; это разные признаки интеграции. Итоговый внешний реестр
вместе с PR фиксирует также окончательный SHA новой интеграционной ветки.

## Способ интеграции

Создана `integration/research-4-3` от актуального origin/main. Выполнен
`git merge --no-ff --no-commit origin/research/h1-h2-comparison-4-3`.
Три конфликта: tools/context/README.md, context_stats.py и tests/test_context_stats.py.
Их delta в research-ветке только возвращала старые пути зависимости. После
проверки каждого конфликта сохранены актуальные версии main; canonical imports
затем уточнены отдельно и проверены тестом с poisoned short-name modules.
Механического выбора всей стороны дерева не было.

Merge-коммит интеграции имеет родителей исходный main и исходный H1/H2 HEAD.
Все три исследовательских SHA сохраняются; power-asymmetry включается через
ancestry H1/H2. Исторические ветки не менялись, force push/reset/rebase и их
удаление не выполнялись. Интеграционный PR следует окончательно слить через
**Create a merge commit**, чтобы source SHA стали предками main. Squash/rebase
не обеспечивают это свойство. Сам main этой работой не изменяется.

## Что сохранено и что адаптировано

Все 37 исторических документов/PNG из docs/research-4.3 побайтно совпадают с
`3db6311`: 12 Markdown и 25 рисунков. Сохранены отрицательные выводы, протоколы,
distribution/host/group/pair/topology/equal-budget/risk-set comparisons и все
оговорки о псевдоразметке. Historical reports не переписаны задним числом.

Исследовательские channels.py, stats.py, comparison_stats.py, исходные 15 тестов,
platform_info.py и forest_benchmark/main.go сохранены без изменения математического
поведения. Новые изменения ограничены dependency imports, безопасными output
paths, test discovery, read-only reproduction и действующими инструкциями.

Vendor/research41 содержал четыре Git blob, идентичных tools/diagnostics текущего
main. Их SHA приведены в [README](../../tools/research43/README.md). Сначала
проверены identity, импорты, тесты, scripts и numeric reproduction, затем удалены
ровно эти четыре копии. Оригинальные tools/diagnostics и dependencies не менялись.
Context/research43 теперь используют tools.diagnostics.diagnostic_stats; short-name
module cache не может незаметно подставить старую реализацию этим consumers.

Проверен вывод генераторов: после удаления нового заметного historical notice
все шесть regenerated Markdown побуквенно совпали с original reports. Научные
числа/формулы не менялись. Новый report-dir обязателен и должен отсутствовать;
historical docs защищены. Audit по умолчанию stdout-only, явный JSON создаётся
exclusive. analyze figures по умолчанию внутри нового output. При отсутствии
platform.json новая машина не записывается в исторический experiment.

На Windows выявлена CRLF-проблема: два протокола перестали совпадать с SHA,
сохранёнными в Stage II manifest. Проверено, что raw Git LF bytes точно дают
ожидаемые SHA. Восстановлены эти исходные bytes и добавлено узкое правило
`.gitattributes: docs/research-4.3/*.md text eol=lf`. Проверка SHA не ослаблялась.

## Наблюдаемые проверки

| Проверка | Результат |
|---|---|
| go test -mod=readonly -count=1 ./... | PASS |
| go build -mod=readonly ./... | PASS, включая сохранённый forest_benchmark |
| go vet -mod=readonly ./... | PASS |
| Полный pytest, включая E2E с собранным replayer | 110 passed, 5 PostgreSQL tests skipped (TEST_DATABASE_URL не задан) |
| Новые integration tests | Canonical imports при poisoned sys.modules; защита исторических путей; exclusive audit; mandatory report-dir |
| Context read-only reproduction | PASS: прежние thresholds, events, runs и group/host counters |
| Stage I independent audit | Точно равен historical audit.json; 260560 temporal checks, 6050 matched controls |
| Stage II independent audit | Точно равен historical audit.json: H1 raw score/flags/margin, все определённые H2 scores, D1 parameters, matched/risk statistics, Holm16, equal-budget |
| Полная pair/topology regression | Все observed signal/onset pairs и 1999×8×2=31984 сохранённых перестановочных значения совпали |
| Runtime B1 на реальных D1/D2 | PASS: 288 thresholds exact; все 829440 D2 scores/решений совпали; 14341 срабатывание |
| H2 counts | 6012 positive, 5895 negative, 11907 any; D1-only calibration; D2 не подгонялся |
| Сохранность | 117 защищённых файлов data/results/B1-config, 2958333134 bytes: SHA, размеры и состав до/после совпали |

Go 1.27.2, Python 3.12.14, прежние venv/diagnostics packages. Зависимости не
обновлялись. Go cache/temp, pytest temp, новые audit JSON и regenerated reports
расположены отдельно вне репозитория. Большие экспорты, обучение и подбор
параметров не повторялись. Полный performance benchmark заново не запускался:
сохранены его код/результаты, сборка проверена, старые времена не объявлены новыми.
Пять DB tests не выполнялись, новые БД не создавались. Новый датасет не скачивался.

Production B1 (`internal/local`, `cmd/local`, configs/local-b1…), internal/analysis,
IF, statistical и tools/diagnostics имеют **нулевой diff относительно исходного
main**. Данные, модели, thresholds и исторические results не изменились.

## Научные ограничения и независимое review

H1 сохраняет абсолютный score и отдельные absolute/context flags без OR.
H2 остаётся исследованием: доминирование PSU, зависимость от фиксированного
60 s лага и положительные echoes после отрицательных изменений ограничивают
его самостоятельный смысл. Независимой разметки аппаратных неисправностей нет;
статистические совпадения и F1_ref не являются качеством реальных отказов.
H2 не подключён в cmd/local, GroupEvent или четвёртый критерий. Новый групповой
алгоритм/паспортный detector/распределённая КР не реализованы.

Отдельный Inspector review выявил неоднозначные short-name imports и отсутствие
parent directory для нового audit-output. Исправлены, добавлены проверки.
Повторное review текущего diff: no actionable findings в назначенном scope.
Inspector не запускал исследования/тесты; главный выполнил и проверил все результаты.
Роль: Inspector, gpt-6-luna/low configured по TOML; runtime metadata не подтверждены.
Другие новые субагенты в этом задании не запускались.

Реально оставшиеся отличия до слияния PR: main ещё не содержит №4.3. В интеграции
все полезные результаты сохранены; сознательно исключены только идентичный vendor
и возврат старых context dependency paths. H2 сохранён как исходник, но его
production-подключение не переносится по научным ограничениям. После review
и Create a merge commit новых источников из этих веток переносить не потребуется.
