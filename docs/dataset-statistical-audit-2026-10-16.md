# Аудит предобработки и статистического обучения

Дата проверки: 20.10.2026. База: `44be030f1b2bf254a576184e33776106f6ed3627`
(`main` после PR №11 и №12). Ветка: `fix/dataset-statistical-audit`.
Имена файлов и строки в задании относятся к предыдущей версии исходников;
ниже участки идентифицированы также именами функций.

## Результат и границы изменения

Математической ошибки в `FitStatistical` не обнаружено. Его production-код,
порядок вычислений, параметры и сохранённые профили не менялись. Исправлены
проверка файловой системы назначения и охват SQLite scratch; в новых manifest
добавлены явные знаменатели доступности. Отбор групп и преобразование F18 сохранены.
Полный Summit не пересобирался; PostgreSQL не запускался и не изменялся.

До исправлений сохранён [baseline SHA](dataset-statistical-audit-v1/baseline-sha256.json):
413 файлов, 2 998 602 879 байт, включая raw/prepared, manifest, статистические
профили, IF, B1, групповые профили и результаты предыдущих исследований.
После проверки допускаются изменения только трёх файлов Builder. Все остальные
410 файлов совпадают с исходными SHA. Новые тесты и отчёты в этот список не входят.
Исторические SHA-реестры и manifest не переписываются.

## Журнал замечаний

| Замечание | Что делает код | Ошибка или нет | Что проверено | Что исправлено |
|---|---|---|---|---|
| `pa.array(sorted(hosts))` | Строит множество значений для Arrow membership | Лишняя сортировка; математической ошибки нет | Порядок/дубли value_set не меняют `is_in`; вызывающие функции уже сортируют hosts | Удалена повторная сортировка; пустой, повторный и некорректный выбранный hostname явно отклоняются |
| `guard(target, 256*1024**2)` | Требует свободные 5.25 GiB перед очередным входным batch | Раньше проверял anchor диска, не mount назначения; до открытия SQLite проверки не было | Граница равенства, новый путь, отсутствующий диск, отказ до создания SQLite | Ближайший существующий предок, отдельная проверка scratch и target до работы и во входном цикле |
| `guard(output, 1024**3)` | Стартовый запас 1 GiB сверх floor 5 GiB | Консервативное соглашение, не оценка размера полного задания | Константы и место вызова в обеих ветках | Значения сохранены; аналогичная проверка добавлена в full build |
| `rows/valid/invalid` | Считает наблюдаемые строки, полные F18 и неполные наблюдаемые строки | Формулы корректны; отсутствующие строки не относятся к invalid | Восемь наборов на полной суточной сетке | Старые значения сохранены, добавлены явные coverage |
| `missing_features` | NULL в каждом столбце среди существующих строк | Корректно, но не отражает полностью отсутствующий host-tick | Пропуски строк отдельно/вместе с NULL, NaN/Inf | Добавлен total unavailability, учитывающий 18 координат отсутствующей строки |
| `group_quality` full | `r/(3*18*8640)`, `m/(r*18)` | Корректно для трёх UTC дней, второй показатель условный по наблюдаемым строкам | 1/3 дня, пропавший tick, согласованность выбранных групп с общими суммами | Общий helper использует фактическое число дней; старые поля сохранены |
| `group_quality` pilot | `r/(18*8640)`, `m/(r*18)` | Ошибочного множителя 3 не было | Реальный вызов pilot и full на синтетике | Добавлены те же новые метрики; ranking не менялся |
| CPU core mean | Среднее конечных доступных core readings | Корректно по действующему контракту, не означает наличие всех cores | 1/2 core, 0/2, NULL/NaN/Inf, неизвестный count=-1 | Не изменялось |
| Timestamp/ключи | UTC, точность us, сетка 10 s, один день и уникальная пара host/time | Корректно; сортировка выполняется позже на диске | NULL, off-grid, два дня, потеря ns, дубликаты, reverse input | Не изменялось |
| Median/MAD | Две сортировки одного столбца с преобразованием in-place | Корректно для чётного/нечётного N | Отрицательные/положительные значения, независимые ожидаемые Median/MAD/covariance | Не изменялось |
| Центр/covariance/SVD | Нормализация, Welford, ddof, усечённая псевдообратная | Корректно, включая singular/zero rank node profile | Существующие и новые unit tests, точная сверка всех полей реального профиля | Не изменялось |
| Q99 | Inverse empirical CDF: элемент `ceil(.99*N)-1` | Корректно, строгий trigger `D²>Q99` | Граница равенства, сохранённые решения на всех D1 states | Не изменялось |
| Неизменность проходов | Сравнивает количество, но доверяет immutable Data | Ограничение контракта: равное количество не доказывает равенство данных | Изменённое значение при том же N, отдельный SHA-вариант benchmark | Production hashing не добавлялся; риск и стоимость документированы |
| Ресурсы | Колонки O(18N), три повторных чтения, exact sorting | Стоимость обусловлена алгоритмом и reader; SVD не bottleneck | Go benchmem, Windows peak working set/I/O, CPU/alloc pprof | Оптимизации математического ядра не принимались |

## 1. Membership, hostname и порядок

`hosts` приходит из `select_groups`: 18 однозначных позиций 1..18 каждой
пригодной группы, присутствующих во всех переданных днях. В `build` и
`build_pilot` общий список снова сортируется. Третья сортировка внутри
`prepare_day` не нужна: `pc.is_in(array,value_set=...)` проверяет принадлежность,
не сортирует строки исходного массива. Пример: value_set `[a02n01,a01n01]`
и `[a01n01,a02n01,a01n01]` дают одинаковую маску на одном входе.
Избавление от сортировки убирает временный Python список из H ссылок; Arrow
value_set остаётся необходимым. Для H=288 экономия мала, это упрощение, не
заявление о значительном ускорении. Выход по-прежнему сортирует SQLite по
`timestamp,group_id,hostname`; межхостовая сортировка лексикографическая.

`parse_hostname` допускает одну/две цифры group/node и группы a..h, включая 00;
непустая строка и node=1..18 обязательны. Не вводился более узкий физический
диапазон. Алиасы `a1n1` и `a01n01` отображаются в одну структурную позицию:
если встречаются оба, `select_groups` исключает неоднозначную группу. Точные
дубликаты `(hostname,timestamp)` отклоняются bitmap-проверкой `scan_day` и
PRIMARY KEY при подготовке. Неполный host-day не исключается автоматически,
но целиком отсутствующий host-day исключает его группу из пересечения.

## 2. Дисковая защита

| Величина | Байты | GiB | Смысл |
|---|---:|---:|---|
| `MIN_FREE` | 5 368 709 120 | 5 | Дополнительный защитный floor |
| Default reserve | 67 108 864 | 0.0625 | Запас на ближайшую операцию |
| Input batch reserve | 268 435 456 | 0.25 | Консервативный запас при заполнении SQLite |
| Startup reserve | 1 073 741 824 | 1 | Начальный запас для Builder |

Проверка: `actual_free >= MIN_FREE + reserve`. При равенстве запуск разрешён.
Это **не** предварительное резервирование пространства и **не** доказательство,
что весь оставшийся день поместится. Источник констант — engineering policy
в коде; измеренного обоснования их оптимальности в репозитории нет. Они не
менялись. Небольшой fixture может быть заблокирован при free<5 GiB, хотя сам
поместился бы: это ожидаемый консервативный эффект, а не оценка его размера.

Раньше `Path.resolve().anchor` проверял корневой том; mount ниже anchor мог
принимать запись на другой filesystem. Теперь проверяется ближайший
существующий предок назначения, включая разрешённые symlink/junction.
Несуществующий filesystem завершается ошибкой, а не поиском предка без конца.
Проверка не устраняет гонку с другим процессом, расходующим свободное место.

Фактический рабочий объём включает одновременно raw (уже на диске), SQLite,
ранее подготовленные временные дни, новый Parquet и, при явной замене,
старый набор до публикации. Scratch создаётся рядом с output, а не внутри
него: при mounted output тома могут различаться. Теперь проверяются оба пути.
Полный build получает стартовую проверку после read-only scan/selection;
pilot — до scan. `prepare_day` проверяет пути до SQLite, перед каждой входной
партией и output перед открытием writer/каждой выходной партией.

SQLite использует cache_size=-32768 (примерно 32 MiB page cache), temp_store=FILE,
WITHOUT ROWID и составной PRIMARY KEY. Нынешний ORDER BY совпадает с этим
ключом; дополнительные SQLite TEMP-файлы не имеют отдельного capacity budget.
При изменении SQL с внешней сортировкой потребуется отдельно контролировать
том SQLite temp directory. Финальные небольшие manifest и `os.replace` также
не являются отдельной гарантированной квотой. Ошибка I/O по-прежнему возможна;
невозможно считать успешный guard гарантией завершения всего задания.

[Синтетический замер](dataset-statistical-audit-v1/builder-equivalence.json),
18 432 host-ticks, seed=20261016: SQLite 1 482 752 B, Parquet 268 122 B.
Это не оценка размеров реального полного дня и не основание уменьшать floor.

| Синтетическая подготовка | Исходная | После |
|---|---:|---:|
| Время одного прогона, s | 0.2199 | 0.2274 |
| Вызовы guard | 6 | 12 |
| SQLite/Parquet bytes | одинаковы | одинаковы |
| SHA Parquet | `c16a086fb8235f627cd2e359d1597e896d3a4436d3ab9cf0d6af1cfbb5068390` | тот же |

Разница времени одного короткого прогона не доказывает изменение скорости.
Удвоение проверок здесь объясняется отдельным scratch и startup check.

## 3. Определения доступности и версия manifest

Пусть H — число выбранных хостов, d — число полных UTC дней,
E=H*d*8640 — ожидаемые host-ticks, r — наблюдаемые строки,
v — строки со всеми 18 конечными F18, m — NULL-координаты среди r строк.

| Поле | Формула/значение | Знаменатель |
|---|---|---|
| `rows`, `valid`, `invalid` | r, v, r-v | Наблюдаемые строки |
| `missing_samples` | E-r | Ожидаемые host-ticks |
| `missing_features[f]` | NULL координаты f среди строк | Только наблюдаемые строки |
| `coverage` (legacy), `sample_coverage` | r/E | Все ожидаемые host-ticks |
| `complete_f18_coverage` | v/E | Все ожидаемые host-ticks |
| `feature_missing_fraction_observed` | m/(18r) | Координаты наблюдаемых строк |
| `total_unavailable_feature_positions` | 18(E-r)+m | Счётчик координат |
| `total_feature_unavailability_fraction` | [18(E-r)+m]/(18E) | Все ожидаемые F18 позиции |

Например, E=8640, один отсутствующий tick и один NULL в другой строке:
r=8639, v=8638, invalid=1, missing_samples=1, m=1; sample coverage=8639/8640,
complete coverage=8638/8640, observed feature fraction=1/(8639*18),
total unavailable=19. Один пропавший tick без NULL имеет m=0, но 18
недоступных ожидаемых позиций. Начальные/конечные gaps учитываются относительно
целого UTC дня, а не расстояния между первой и последней наблюдаемыми строками.

Сохраняется `group_quality.missing_fraction=m/(18r)`; его смысл не расширен.
`coverage` по-прежнему sample coverage. Новые counters/fractions добавлены
одинаково в дневную и групповую статистику. При r=0 условная fraction равна
JSON null; остальные доли определены. Неконсистентные counts отклоняются,
доли не обрезаются искусственно к [0,1]. Новая версия:
`manifest_version=dataset-manifest-v2`, `builder_version=1.1.0`;
`schema_version=F18-v1` и Parquet metadata не меняются. Старые manifest без
`manifest_version` остаются допустимыми для существующих читателей. Это
аддитивная совместимость для project readers, не гарантия стороннего strict
JSON-schema, запрещающего дополнительные поля.

Для одной группы E=d*18*8640: 155 520 при d=1 и 466 560 при d=3.
Pilot не использовал трёхдневный знаменатель и раньше. Новый helper использует
`len(days)`. `group_quality` описывает **все** eligible группы, дневные totals —
только выбранные: при проверке сумм нужно фильтровать quality по selected_groups.
Тесты проверяют суммы counters и те же выбор/порядок групп в обоих режимах.

Важно различать Builder day и учебные окна: существующий `D1.parquet` содержит
сутки, а statistical D1 — фиксированные первые 8 часов, 288*2880=829 440
наблюдений. Суточный denominator Builder не заменён восьмичасовым.

## 4. Остальная предобработка

- `clean_numeric`: cast в float64, NULL/NaN/+Inf/-Inf → NULL. Нулевой finite
  reading сохраняется как наблюдение. Отрицательные и большие конечные значения
  не отклоняются: это numerical availability, не паспортная достоверность.
- `mean_cores`: `sum(finite cores)/count(finite cores)`; нули в аккумуляторе
  только identity. При count=0 результат NULL; overflow суммы отклоняется.
  Частичный CPU mean является доступной F18-координатой; число cores сохраняется.
  Готовый source mean не пересчитывается, count=-1 означает неизвестность.
- `project_batch`: порядок FEATURES строго PSU0/1, CPU0/1 power, GPU0..5 power,
  CPU0/1 mean temp, GPU0..5 core temp. Bit i availability_mask соответствует
  FEATURES[i]; is_valid равен mask==(1<<18)-1. Пропуски не заполняются нулями.
- `raw_columns`: explicit timestamp/hostname и mapped features/cores по именам;
  порядок raw mapping не меняет канонический порядок выходных признаков.
  `load_mapping` запрещает отсутствующие, нечисловые и повторно используемые
  raw feature/core columns. Имена cores не угадываются.
- `timestamp_utc`: aware timestamp сохраняет instant при приведении к UTC;
  naive требует явный timezone, DST ambiguity/nonexistent отклоняются.
  Safe cast в us не допускает потери ns. NULL отклоняется.
- `scan_day`: UTC сутки, divisibility 10 s, уникальный host/slot. Bitmap:
  8640 bits=1080 B на hostname плюс Python overhead. Чтение BATCH_SIZE=8192
  ограничивает память; сохраняется host-level статистика, не весь raw.
- `select_groups`: пересечение hosts всех дней, 18 однозначных позиций,
  сортировка `(-observed_rows, missing/(rows*18), group_id)`.
  Диагностический helper не участвует в этом ranking.

**Открытое ограничение отбора:** в трёхдневном режиме наличие/missingness D2/D3
влияет на выбор обучаемой когорты D1. Это availability-based selection bias,
даже без использования anomaly scores. Исторический отбор не меняется.
Для будущей prospective оценки следует заранее выбрать топологию либо
зафиксировать когорту только по D1, сохранив новую версию manifest/protocol.
Утверждать независимость такой трёхдневной выборки от D2/D3 нельзя.

## 5. FitStatistical: формулы и пограничные случаи

`Data` обязан повторно открывать одну immutable последовательность полных
конечных D1 observations. Входной window равен фиксированному NIR D1;
проверка timestamps выполняется во всех трёх проходах, D2/D3 отклоняются.

1. Первый проход хранит N значений каждой из p=18 координат. Допускаются только
   finite полные состояния; N>ddof. Сортировка делается in-place в каждом cols[j].
2. Для нечётного N median=x_sorted[N/2]; для чётного —
   x_sorted[N/2-1]/2+x_sorted[N/2]/2. Раздельное деление предотвращает overflow
   суммы. На экстремальных subnormal остаётся обычное округление float64;
   реальные физические координаты Summit не близки к этому диапазону.
3. Та же память заменяется на abs(x-median), сортируется повторно;
   MAD=median(abs deviations). Исходный столбец дальше не нужен: Data перечитывается.
   Сортировка исходных значений не означает сортировку модулей отклонений:
   `[-5,1,9]` → median=1, deviations в этом порядке `[6,0,8]`, MAD=6.
   Для `[-5,1,3,9]`: median=2, MAD=4. Вторая сортировка нужна текущей
   sorted-median реализации. Альтернатива order-statistic selection возможна,
   но не внедрялась без отдельного доказательства выигрыша/эквивалентности.
4. Scale_j=max(1.4826*MAD_j,1e-4); z_ij=(x_ij-median_j)/Scale_j.
   Единица scale совпадает с исходной координатой (W либо °C), z безразмерен.
   Floor — численное соглашение, не разрешение датчика и не hardware limit.
5. Второй проход: delta=z_n-mu_(n-1), mu_n=mu_(n-1)+delta/n;
   C_ij += delta_i*(z_n,j-mu_n,j) для нижнего треугольника. После прохода
   Sigma=C/(N-ddof), зеркально копируется верхний треугольник. Это Welford
   covariance; порядок суммирования не менялся. ddof допускает 0/1,
   сохранённый профиль использует **1**. Для примеров выше сумма квадратов
   сырых центрированных данных соответственно 296/3 и 100; тест сверяет
   covariance=(эта сумма)/[(N-ddof)*Scale²] независимо от Welford.
6. Sigma=U diag(s) Vᵀ; Gonum rank с относительным cutoff 1e-12;
   Sigma⁺=V diag(1/s retained,0 discarded) Uᵀ. Rank zero даёт нулевую
   Moore–Penrose inverse. Это существующий **узловой** статистический профиль;
   требование rank=10 группового B сюда не переносится.
   При singular covariance расстояние не чувствительно к компоненте в её
   nullspace; при rank=0 оно равно нулю даже для нового экстремума. Это
   ограничение псевдообратной, а не доказательство нормы. Реальный проверенный
   узловой профиль имеет полный rank=18.
7. Третий проход вычисляет D²=(z-mu)ᵀ Sigma⁺ (z-mu).
   Малое отрицательное roundoff обнуляется только при
   -D²<=1e-12*max(1,sum(abs(terms))); overflow/большое отрицательное отклоняется.
8. Q99 — inverse empirical CDF: sort-copy distances и элемент ceil(.99*N)-1.
   Интерполяции нет, бинарное решение строго `D²>Q99`.
9. Validate проверяет finite metadata, scale, симметрию, PSD/eigenvalues,
   повторно rank/SVD и относительную Frobenius-погрешность inverse<=1e-10.
   SaveNew не перезаписывает существующие результаты. Сам Fit ничего не сохраняет.

Обычные sort.Float64s не копируют cols[j]; MAD переиспользует тот же slice.
EmpiricalQuantile сознательно копирует distances, поскольку публичная функция
обещает не менять вход. Двойная сортировка обоснована выбранным exact алгоритмом,
но не является единственным математически возможным способом получить Median/MAD.

### Неизменность входа

Сравнение counts ловит исчезнувшую строку, но не изменение значения или порядка.
Тест оставляет timestamps/N=3 и меняет только третье значение на третьем проходе:
`[-1,0,1]` → `[-1,0,3]`. Текущий Fit принимает его и получает Q99, увеличенный
в 9 раз. Это нарушение предусловия Data; не корректная новая обучающая выборка.
Перестановка сохраняет Median/MAD и точную covariance математически, но может
изменить float64 Welford в последних разрядах, поэтому порядок тоже входит в
immutable contract. Source проверяет SHA при OpenSource, но не хеширует заново
каждое повторное чтение; технически конкурентная замена файла не запрещена.

В отдельном benchmark SHA256 обновлялся по timestamp(us) и 18 IEEE754 values
каждой observation; три digest совпали. Этот вариант не добавлен в production.
Один paired замер: 6.2631 s без него и 6.6942 s с ним (+6.9%). Порядок запусков,
кэш ОС и нагрузка не рандомизированы; это оценка стоимости, не уверенный эффект.
Для текущих immutable local artifacts, input SHA и pre/post audit snapshots
обязательное hashing не принято. Для сменяемых/внешних источников нужен
отдельный контракт snapshot или sequence digest; молчаливо доверять count нельзя.

## 6. Измерение на реальном D1

[Исходные измерения](dataset-statistical-audit-v1/benchmark.json).
Windows amd64, Go 1.27.2, i7-12650H. Один iteration на вариант, без обучения IF
и без D2/D3 fitting. OpenSource checksum и дополнительная проверка решений
находятся вне timed fitting; allocs/op также относятся к timed fitting.
Временные границы сняты Data wrapper, production Fit не инструментирован.

| Фаза неизменённого FitStatistical | s |
|---|---:|
| Первый проход: reader + сохранение столбцов | 1.7721 |
| Median/MAD, scaling | 0.7049 |
| Второй проход: reader + Normalize/Welford | 1.8316 |
| Деление covariance, SVD, inverse | 0.0020 |
| Третий проход: reader + distances | 1.8786 |
| Q99 и Validate (включая повторный SVD) | 0.0732 |
| Полный timed Fit | 6.2631 |

После изменения Fit таблицы нет: **Fit не менялся**. Повторный запуск с pprof
занял 6.7444 s, что показывает вариабельность и instrumentation overhead.
Публичные интерфейсы не позволяют отдельно точно выделить Q99 из Validate;
в таблице явно указан совместный интервал. Аналогично reader/Welford и
reader/distances не выданы за изолированное время чистой арифметики.

Прочитано 829 440 состояний в каждом из трёх проходов, всего 2 488 320.
Logical payload F18: 358 318 080 B (не compressed Parquet I/O).
Timed allocations: 1 575 923 408 B/op, 62 465 966 allocs/op; это суммарно
выделенные байты, не resident memory. OS peak working set всего benchmark
процесса ~334.3 MiB (350 502 912 B); он включает оба варианта и проверки.
Whole-process wall=18.54 s, Windows read transfer counter=355 223 793 B
включает OpenSource, оба fits и оба дополнительных scans проверки решений.
Cached read transfers не интерпретируются как физическое чтение диска и не
делятся искусственно на три. Размер исходного полного Parquet — 93 075 717 B.

CPU pprof всего профилируемого процесса (fit+проверка) показывает 65.86%
cumulative в WindowReader.Next, 8.56% в DistanceSquared; эти доли пересекаются
с дочерними вызовами и не складываются как независимые категории. Allocation
profile показывает рост append-колонок, reflection/Parquet reconstruction и
hostname parsing; SVD не является главным потребителем времени. Компактный
вывод сохранён в [profiling.json](dataset-statistical-audit-v1/profiling.json),
сырые cpu/mem profiles остаются ignored `.cache/`.

Память Fit: O(pN+p²), временные distances/copy — O(N), sorting
O(pN log N), covariance/distances O(Np²), SVD O(p³), p=18.
Только конечные значения колонок занимают 18*N*8=119 439 360 B;
growth append и reader создают дополнительные временные allocations.
Preallocation, reader allocation reduction, order-statistic selection и
in-place private Q99 могут быть будущими отдельными измеренными изменениями.
Основания переписывать проверенное ядро в этом аудите нет.

## 7. Проверки воспроизводимости

- Исходные Go test/build/vet прошли; исходные Python: 123 passed, 6 skipped.
  Первая sandbox-попытка столкнулась с доступом к старому tmp и пакетам;
  повтор с доступом к существующим зависимостям прошёл. ACL не менялись.
- Новые tests: суточные complete/null/absent/both/host gap/edges/partial cores/
  nonfinite; zero denominator; оба Builder mode; group sums; host-set
  equivalence; disk boundary/scratch/unavailable filesystem; time precision;
  odd/even Median/MAD/ddof; межпроходные counts и same-count drift.
- Real D1: точное сравнение **всех** полей freshly fitted и исторического
  профилей через reflect.DeepEqual: Median/MAD/Scale/Mean/Covariance/Rank/
  PseudoInverse/Q99. Проверены все 829 440 D1 distances и бинарные решения:
  8294 positives, rank=18, Q99=77.704896906807022. Допуск не понадобился.
- Независимое чтение исторических timeline/events: R=899, B=3260, RB=682,
  delta=0 events=285, сумма positive_ticks событий=682, Y везде unknown.
- Итоговые результаты test/build/vet, Python/e2e, B1 и SHA — в
  [validation.json](dataset-statistical-audit-v1/validation.json).
  Нет запуска PostgreSQL, массового импорта, замены prepared или моделей.

### Повторение

Из корня репозитория; Python должен иметь зафиксированные project dependencies.
Для каждой команды выбрать новый output, существующие результаты не затирать.

```powershell
go test ./...
go build ./...
go vet ./...
python -m pytest -q tools/dataset/tests
python tools/dataset/audit_snapshot.py verify docs/dataset-statistical-audit-v1/baseline-sha256.json
python tools/dataset/audit_builder_equivalence.py --output results/audit-builder-new.json
go test -c ./internal/experiment -o .cache/statistical-audit.test.exe
python tools/dataset/audit_benchmark.py --output results/audit-fit-new.json
$env:LOCAL_B1_REAL='1'
go test -v ./internal/local -run TestRealB1D2MatchesResearch -count=1
```

Для pprof задать NIR_AUDIT_PARQUET/MANIFEST/PROFILE абсолютными путями, затем:

```powershell
& ./.cache/statistical-audit.test.exe '-test.run=^$' '-test.bench=^BenchmarkFitStatisticalAudit/sequence_sha256=false$' '-test.benchtime=1x' '-test.benchmem' '-test.cpuprofile=.cache/fit.cpu' '-test.memprofile=.cache/fit.mem'
go tool pprof -top .cache/statistical-audit.test.exe .cache/fit.cpu
go tool pprof -top -alloc_space .cache/statistical-audit.test.exe .cache/fit.mem
```

SHA snapshot save выполнялся **до** изменения Builder. Не запускать save поверх
сохранённого baseline. Для точного повторения baseline-builder сравнения нужен
исходный commit в Git object database, иначе `git show` явно завершится ошибкой.

## 8. Закрыто, открыто, решения

**Закрыто:** membership order/дубли; смысл дисковых констант; mount/scratch
проверки; точные availability counters/denominators; pilot/full consistency;
F18/CPU/time/uniqueness; математика Fit; реальное exact profile/decision parity;
замер времени, allocations, peak memory и I/O; сохранность baseline событий.

**Открытые ограничения:** selection bias при многодневном отборе;
immutable Data не доказывается одним count; отсутствие capacity estimate на
полное задание; process aggregate profiling не равно чистой latency математики;
PostgreSQL integration без тестовой БД не выполнялась. Это не скрытые PASS.

**Решения пользователя для отдельной версии:** D1-only/preregistered cohort
для будущего prospective исследования; обязательный sequence digest или
snapshot adapter для изменяемого источника; необходимость отдельной работы
по reader allocations/preallocation/selection algorithms; измерение capacity
перед возможным пересмотром floor. Ни одно из этих решений здесь не принято
за пользователя. R/B/Y, IF/B1, распределённый контракт и исторические результаты
остаются прежними.

Роль: Orchestrator GPT-6.1 Sol High (configured). Один Inspector GPT-6 Luna Low
(configured), mode explore: read-only математическая проверка Fit и Data
контракта; без выполнения тестов и правок. Приёмка, integration review и все
выполненные проверки — основная сессия. Новых зависимостей нет.
