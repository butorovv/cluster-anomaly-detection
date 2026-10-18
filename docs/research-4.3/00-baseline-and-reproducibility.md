# Этап 0: baseline и воспроизводимость

Дата 14.10.2026. Baseline **совпадает** с ТЗ. Новый полный Go-export A0/Mahalanobis D2 побайтно совпал с экспортом №4.1. B1/B2 и seed43/44 проверены повторной арифметикой неизменных экспортов и независимым прямым обходом сохранённых деревьев. **Повторное обучение всех шести лесов в этой работе не выполнялось.**

## Git и последовательность включения

| Ветка после успешного fetch | SHA | Состояние |
| --- | --- | --- |
| main | 1dfb7c1f8b011b64a8fdebe4de4cdaafc3438940 | база обоих исследований |
| research/d2-anomaly-diagnostics | 79a144125ba5a05d21a999516e210ba6e604e6e2 | 2 собственных коммита; не в main/4.2 |
| research/context-aware-isolation | 98aab5865a9ee8d0d59c8fe51954047abab32ef8 | 3 собственных коммита; не в main |
| research/power-asymmetry-4-3 | база 98aab586… | текущие этапы 0/I |

Рекомендация: отдельно согласовать включение №4.1, затем перенести/проверить №4.2 на обновлённой базе, затем №4.3. Ветки 4.1/4.2 — соседние, merge-base равен main. Merge/cherry-pick не выполнялись. №4.3 создан от №4.2. Минимальная зависимость 4.1 закреплена четырьмя побайтными исходниками в tools/research43/vendor/research41; это явная зависимость, без объединения историй и без переноса старых отчётов.

## Протокол и сохранность

D1: 18.01.2022 [00:00,08:00); D2: [08:00,16:00), assumed UTC. В каждом 288×2880=829440 состояний, полный F18. Последняя отметка D2 2022-01-18T15:59:50.000000. D3 не участвует в обучении, scoring, статистике или калибровке. Hash полного Parquet проверяет сохранность байтов. timezone_verified=false; геометрия групп hostname не равнозначна доказанному графу инфраструктуры.

Версии: statistical-v1, isolation-forest-v1, physical-v1, isolation-calibration-v1; лес 100 деревьев, ψ=256, depth=8, seed42 (дополнительно 43/44). Q99 — наблюдение с индексом ceil(.99n), строгий знак >, без интерполяции.

| Метод | D2 сигналов | 4 a02 | Совпадений с переходами | Доля событий |
| --- | --- | --- | --- | --- |
| A0 historical | 12847 | 87.33% | 110 | 1.58% |
| A0 D1-Q99 | 8153 | 100.00% | 1 | 0.01% |
| B1 | 14341 | 1.64% | 2352 | 33.71% |
| B2 | 14123 | 0.08% | 2625 | 37.62% |

Mahalanobis D²>77.70489690680702: 9880 состояний. IF/Mahalanobis: TP_ref=2607, FP_ref=10240, FN_ref=7273, TN_ref=809320. F1_ref=0.2294187530250363 — согласование критериев, не точность отказов.

| Метод | Внутригрупповые пары | Среднее 1999 разбиений | Отношение | Точное ожидаемое отношение |
| --- | --- | --- | --- | --- |
| A0 D1-Q99 | 7701 | 469.268 | 16.4107 | 16.8824 |
| B1 | 87963 | 45315.1 | 1.94114 | 1.94186 |
| B2 | 100056 | 46533.3 | 2.1502 | 2.15132 |

Сохранённые перестановки seed4202 заново арифметически оценены; новые разбиения не генерировались. Прежние 1999 временных сдвигов seed42 дают Holm64 p=.032 для pair-bins a12–a16. Это проверка воспроизводимости прежнего контроля.

## SHA-256 входов и производных артефактов

| Вход | SHA-256 |
| --- | --- |
| data/prepared/summit-D1-pilot/D1.parquet | cf3fa634448b7147209bebf3b1c20a1a031be5c047678083adda10581ff562e7 |
| data/prepared/summit-D1-pilot/manifest.json | 6d603a5445d1a76be24408eed84933e96a4a10af6c3bfd32471d93ca7dd9f291 |
| results/isolation-20220118-v1.json | 6aa1ca4f2f76b56418aafaa1ea25e6812a3b9fdcc0d309aeed44dc1db03f2da3 |
| results/isolation-calibration-20220118-v1.json | 3c73c85bd121df6bfaade9fa3b37ec517d5546cc520c666e04de2e5f6c61a150 |
| results/physical-20220118-v1.json | 66f3ae9220c00e68d97541ba3b1a5a4bf269008e7aafe0d0e5148efc45225b59 |
| results/statistical-20220118-8h-v1.json | 36da27a4a4f485baa4b1b1b899c26a36efc15401327fd85abc3d63ea3c1ade80 |
| results\context-v1\D1.bin | e8cc48c208fc4ea003a9c29c62d7525325d67f9dc75fc9258665f5b5a90610d6 |
| results\context-v1\D2.bin | 08d90d683924fb58c2bacbbbd356fa0ad785b25c80d0a607e80697f9ce9fd74f |
| results/d2-diagnostics-v1/states.bin | 8b2e710257ed4a1e5cf2d6aa95de8381b29940a9fa448f077dbbea920e92e65c |
| results\context-v1\permutation-controls.npz | 9324630bc810e791aa99221622b759b6963110aea287e65f2ec17b730147bf26 |
| results\context-v1\a0-43.json | 2e327fe9b8eaba3a61e0094ea40df6e23161f97cfea9a4d1f54417fdde05a1f9 |
| results\context-v1\a0-44.json | ba2cc68bb3e4c24140cdb5523a3dd76b4d6c70172a6b0c2c9318cec551a85534 |
| results\context-v1\b2-42.json | 26cbf10064073557474e58d14d9ae1624eb76a62f4cc381df9337ad9a472826e |
| results\context-v1\b2-43.json | a98753c31fd6f1990f8e2dedf5074a2058d08bd7b26e7ada53b86d1f55b82591 |
| results\context-v1\b2-44.json | 0eda0487072cbd983f99249ba5d7d22194f7538648754c5ed6dfc95a9119173a |
| results\context-v1\context-profile.json | a9132016aefaba0529e44a4c4eae243c3d4fdfc8d426bd7e2655110c1163a6af |
| results\context-v1\summary.json | 3643ca60e42e41f3a88b4038169f6ab660f3cad755542aebc8baa433e9edb959 |
| results\context-v1\metadata.json | aa447daa87bb60eccb62de4a371fcdb69c404f095d8ffeec50356faaf6178c5c |
| results\context-v1\thresholds.json | 70de5dc89f88943211bfecc5a534598b92412c127688c1b636aec7b6320907c9 |
| results/d2-diagnostics-v1/shift_controls.npz | ac5c4f4854bb6cc5b84af438786a2510a09f84452ce86c72aecceb970aecef3d |

## Независимая численная проверка

| Проверка | Наблюдаемый результат |
| --- | --- |
| Direct tree oracle | 6 лесов × 2 окна × 1024 состояний; max error=4.44e-16 |
| Mahalanobis прямое матричное вычисление | max error=2.27e-13 |
| Host medians независимой сортировкой | 0 |
| Квантили независимой сортировкой | полное совпадение |
| Новый Go-export D2 | True |
| Новый states.bin SHA-256 | 8b2e710257ed4a1e5cf2d6aa95de8381b29940a9fa448f077dbbea920e92e65c |
| Исходные hashes до/после | совпадают |

Схема №4.1 хранит availability=1 как boolean; №4.2 хранит F18 bitmask=262143. Проверен одинаковый смысл доступности. Timestamp, host, F18, A0 score и D² совпадают по всем строкам. Первоначальная проверка ошибочно сравнила эти разные представления как одинаковые поля и остановилась; проверка исправлена, научные параметры не изменялись, старые результаты не перезаписаны.

## Проверки и восстановление

[Команды и tracked зависимость](../../tools/research43/README.md). [План 0–VI и блокеры](STAGE-PLAN.md). Итоговые checks перечислены в CHECKS.md. Baseline сохранён отдельно: results\research43-v4\baseline.json.
