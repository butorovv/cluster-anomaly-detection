# Фактически выполненные проверки этапа II

14.10.2026. Ветка `research/h1-h2-comparison-4-3` от `aa509f6`,
эксперимент `results/research43-stage2-v1`. Исходные формулы и дополнение
протокола оценки зафиксированы до просмотра нового H2. Новых кандидатов,
лагов, порогов или математической физической модели H3 не реализовано.

| Проверка | Наблюдаемый результат |
| --- | --- |
| Сохранность исходных моделей/экспортов/этапа I | SHA до/после совпадают по всем перечисленным входам |
| H1 abs score | побитно одинаковые829440 float64 значений с A0 |
| H1 A_abs и A_ctx/B1 | полное совпадение с исходными D1-Q99 правилами; OR отсутствует |
| H2 median/MAD/epsilon/scale | точное совпадение с независимым вычислением сортировкой D1 |
| H2 Q99.5 ± | точное совпадение с независимым nearest-rank;25.714307890054826/25.554205460701517 |
| Все определённые H2 score и flags | точное совпадение независимой формулы по реальным D2 |
| Power threshold и masks | исходный физический baseline совпал полностью |
| Primary метрики этапа I | все категории, методы и окна A0/B1/B2/Power воспроизведены |
| Независимая временная арифметика |416896 event/control×method×window проверок совпали |
| Risk/quality cohorts | primary/own/shared N и numerator проверены;6050 matched/928 unmatched |
| Перестановочный расчёт через co-occurrence |80 независимых прямых суммирований по времени/группам совпали |
| Исходные draw counts №4.2 |1999 signal-pair draws A0-Q99/B1/B2 точно совпали |
| Holm16 | независимо пересчитанные p и поправки совпали |
| Equal budgets |15 независимых lexsort проверок, общий valid набор и K/cutoffs совпали |
| Новый Go scoring A0/B2 |829440 D2 строк×2 модели×(прогрев+5 повторов); max absolute score error=0 |
| Python tests рабочей копии |30 passed, exit0 |
| Python tests clean archive |30 passed, exit0; results/ отсутствует, imports только из tracked кода |
| Python compileall с warnings-as-errors |exit0 в рабочей и clean копиях |
| go test ./... |exit0 в рабочей и clean копиях |
| go build ./... |exit0 в рабочей и clean копиях |
| go vet ./... |exit0 в рабочей и clean копиях |
| Go benchmark build/run |exit0; новый файл, без перезаписи прежних моделей/результатов |
| Визуальная проверка |реальное lag-эхо и risk-set график читаемы; остальные3 графика с численными таблицами |
| D3 |только D1.bin/D2.bin; последний timestamp15:59:50; fit guards отвергают mixed D2/D3 |
| Protected paths |diff cmd/internal/db/configs/go.mod/go.sum/vendor пуст |

Первые6 наблюдений каждого окна для delta60 undefined. Не объявлены
нормальными и не включены в denominator H2/Power. В real D1/D2 остальные
состояния полностью доступны. Пропуски, нарушение cadence и проверка
разделения abs/context проверены на маленьких fixtures; они не являются
экспериментальным доказательством обнаружения отказов.

Независимый `audit_compare.py` не импортирует channels/comparison_stats и
проверяет арифметику другим порядком расчёта: сумма физических компонент,
сортировка median/MAD, nearest-rank, прямые temporal loops, direct group
counts и lexsort. CI описательные, не независимые строки; H2-only subset
и lag-эхо — дополнительная описательная диагностика без подгонки thresholds.

Платформа: Windows11/amd64, i7-12650H/16 logical processors, RAM15.63GiB,
Go1.27.2, GOMAXPROCS1, NumPy2.3.5, OPENBLAS_NUM_THREADS1. Один прогрев и
пять повторов арифметики/Go scoring, последовательный порядок. Исторические
тайминги №4.2 не выдаются за сопоставимый новый benchmark. Полный research
91.72s, peak working set781.8MiB — память всего Python процесса, а не одной
модели. Это не этап VI и не окончательная проверка устойчивости.

## Реальные поручения и подтверждение моделей

Orchestrator: GPT-6.1 Sol High — **configured** по `.codex/config.toml`;
runtime metadata текущего потока **NOT VERIFIED**.

Два фактических запуска специализированных проектных ролей:

- `implementer`: GPT-6 Luna, reasoning Medium, **configured**. Ownership
  только channels.py; отчёт о compile PASS. Главный проверил формулы,
  усилил явный reject mixed-window fit и выполнил все тесты/численные checks.
- `inspector`, режим review: GPT-6 Luna, reasoning Low, **configured**.
  Назначенные риски: D1-only calibration, раздельный H1, denominator risk
  sets, permutation/ Holm16, common-valid top-K. Результат: No actionable
  findings. Телеметрию/массивы/D3 не читал, scoring и tests не запускал.

TOML ролей сверены; независимое runtime подтверждение моделей/effort
отсутствует. Не заявляется техническая read-only изоляция inspector.
Test_writer/bug_investigator и каскадные агенты не запускались.

Окончательную научную интерпретацию и приёмку diff выполнил главный.
H2 не выбран по F1 относительно Mahalanobis; Mahalanobis дан только как
auxiliary count/overlap. H3, III, рабочий GroupEvent, D3 и РПЗ не изменялись.
Новые копии зависимостей №4.1 не добавлялись. После II работа остановлена.
