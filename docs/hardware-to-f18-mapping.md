# Сопоставление аппаратных характеристик и F18

18.10.2026, контрольная точка №1. Канонические порядок/имена:
`internal/modules/telemetry/domain/record.go`; исходный ETL:
`configs/feature-mapping.clusterwise.json`. F18 не расширен.

| Raw | F18 | Измерительная граница | Агрегация / единицы | Паспортная совместимость |
|---|---|---|---|---|
| ps0_input_power, ps1_input_power | psu0_power, psu1_power | AC input каждого PSU | 10 s mean; W | DC rating 2200 W неприменим; AC alarm unknown |
| p0_power, p1_power | cpu0_power, cpu1_power | DC CPU consumption; точный rail/package состав unknown | 10 s mean; W | POWER9 SKU/электрический hard bound unknown; TDP не порог |
| p0_gpu0/1/2_power | gpu0/1/2_power | DC GPU consumption при CPU0 | 10 s mean; W | 300 W board specification — справка; cap/погрешность/rail mapping unknown |
| p1_gpu0/1/2_power | gpu3/4/5_power | DC GPU consumption при CPU1 | 10 s mean; W | Та же неизвестность |
| p0_temp_mean, p1_temp_mean | cpu0_mean_temp, cpu1_mean_temp | Среднее температур ядер соответствующего CPU | 10 s mean; °C | Mean не измеряет core maximum; hard bound unknown |
| gpu0_core_temp…gpu5_core_temp | одноимённые поля | GPU core temperature | 10 s mean; °C | SXM2-specific limits/firmware binding unknown; PCIe 83/87/90 °C не переносить |

Семантика и единицы: [авторы исходного датасета](https://github.com/at-aaims/summit_power_and_thermal_data),
DATA-SPECIFIC INFORMATION, Node/CPU/GPU power and temperature;
схема производного файла и дополнительные поля:
[ClusterWise, Data Fields](https://huggingface.co/datasets/MachaParfait/ClusterWise/blob/main/README.md).
10 s — интервал усреднения исходных BMC 1 Hz данных, а не точность датчика.
Часовой пояс источника не установлен; сохранено старое допущение UTC.

## Пять каналов хоста и десять группы

`u=(sum GPU power, sum CPU power, sum PSU AC input, mean GPU core temp,
mean CPU mean temp)`, единицы `(W,W,W,°C,°C)`.
`v=(mean_h u[1:5], population_std_h u[1:5])` по тем же фиксированным 18 хостам;
это смешанные физические единицы. Нормализация B выполняется после агрегации.
CPU mean из двух source means не становится максимумом отдельных ядер.

Нельзя приравнивать PSU AC к CPU+GPU DC: отсутствуют прочие нагрузки, эффективность,
синхронное распределение по двум PSU. Даже известная кривая КПД чужого PSU не
удостоверяет установленный блок. Формула `P_AC=P_DC/eta` требует одной границы
нагрузки, согласованных интервалов и применимой eta; F18 этого не обеспечивает.

## Дополнительные поля — фактически прочитанная raw schema

Локальный raw Parquet имеет 37 колонок; полная схема и SHA зафиксированы в
[диагностике](group-detection-d1-final/diagnostics.json), ключ `raw`.
Прочитаны только D1-значения выбранных 288 хостов; D2/D3 не анализировались.

| Поле | Назначение / доступность | Возможность использования |
|---|---|---|
| node_state | Состояние питания; D1: 829440 Powered On | Контекст доступности, не alarm и не подтверждение нормы |
| xid | GPU error code; D1: 829440 значений -1 | Требует семантики merge, времени и XID; -1 не аппаратный предел |
| label | Производная аннотация; D1: все 0 | Не независимая fault ground truth и не Y |
| allocation_id, job_begin_time, job_end_time | Scheduler/job context | Возможное последующее объяснение режима, не caps/thresholds |
| gpu[0-5]_mem_temp | HBM temperature | Иная величина; вне F18 |
| p[0-1]_temp_min/max | Core extrema | Вне F18; не заменять автоматически mean |
| yymmdd | Дата/partition | Не аппаратная конфигурация |
| threshold/alarm/serial/FRU/power_cap/power_limit | Отсутствуют в схеме данного raw файла | Не восстанавливать по распределению данных |

Перечень исходного полного OLCF набора и локальная производная схема отличаются:
наличие полей в публикации не доказывает их наличие в этом файле.
Дополнительные поля не включены в R/B/Y и не использованы для настройки.
