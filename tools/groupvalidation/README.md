# Group validation v1

Дополнительное разведочное исследование уже изученного D2; production v1 не
меняется. Протокол и все составы контролей предварительно зафиксированы в
`configs/group-validation-protocol-v1.json` и `docs/group-validation-protocol-v1.md`.
Зависимости — существующий `tools/diagnostics/requirements.txt` (закреплённые
NumPy 2.3.5, PyArrow 26.0.0, Matplotlib 3.10.8, pytest 9.1.1).

Из корня репозитория, при наличии SHA-совпадающих исходных файлов PR №10:

```powershell
go build -o bin/group-validation-probe.exe ./tools/groupvalidation/score
python tools/groupvalidation/experiments.py --probe bin/group-validation-probe.exe --output results/NEW_GROUP_VALIDATION
python tools/groupvalidation/audit.py --input results/NEW_GROUP_VALIDATION --output results/NEW_CONTROL_AUDIT.json
python tools/groupvalidation/report.py --input results/NEW_GROUP_VALIDATION --output results/NEW_VALIDATION_REPORT
python -m pytest tools/groupvalidation -q
```

Output всегда новый. Протокол должен быть сохранён в Git до прогона; источник
и SHA протокола проверяются. Полные профили 20 контролей, probe NDJSON, таблицы
свидетельств и matched intervals остаются в ignored results. Компактный отчёт,
параметры и SHA можно опубликовать из отдельного report output.

`common.py` переиспользует проверенные физические агрегаты, robust normalization
и Welford из прежней диагностики. Произвольные составы групп допускаются только
исследовательским Python-инструментом: production hostname validation не меняется.
Перед контролями обязательна numerical parity с Go baseline на D1/D2.

`score` — статический Go probe: JSON-строка содержит id, timestamp, group,
records [{hostname, features[18]}]. Он загружает неизменные IF/B1/group/hardware
профили, применяет `internal/group.Evaluate`, выводит {id,raw}. Только D2,
сетка 10 s, конечные полные F18. Отсутствующие хосты не включаются в records;
JSON null отвергается, не превращается в измеренный ноль. Повторные id,
плохие hostname/длина/время и trailing JSON отвергаются; output O_EXCL.

В запросе probe присутствует только указанная группа. Поэтому outside E
из probe не используется: глобальный S/E восстанавливается в исследовании
из всех исходных B1 states плюс изменённых local результатов и доступности.
При δ=0 интервалы сегментируются по явному positive mask; unknown прерывает
событие. Это исследовательская обработка, а не новая версия production Engine.

Искусственные воздействия не являются fault-разметкой. Baseline-событие внутри
воздействия не засчитывается как новое обнаружение. Нулевой результат и unknown
публикуются без повторного выбора амплитуд/порогов.
