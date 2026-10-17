# Паспортный эталон Summit

Проверено 17.10.2026 по первичным источникам. FACT — опубликованная
характеристика/описание датчика; INFERENCE — вывод о применимости; UNVERIFIED —
отсутствующая привязка к выбранным hostname. Здесь нет нового детектора или
назначенных аппаратных порогов.

## Первичные источники

- [OLCF Summit User Guide](https://docs.olcf.ornl.gov/systems/summit_user_guide.html),
  Summit Nodes, GPUs: конфигурация вычислительных узлов, варианты памяти.
- [IBM POWER9 Introduction, Summit Training Workshop, 2018](https://www.olcf.ornl.gov/wp-content/uploads/2018/12/summit_workshop_thompto.pdf),
  PDF slide 2 (страница PDF 2): шестипроцессорная GPU-конфигурация AC922, SXM2,
  питание; slide 4: активные ядра Summit.
- [NVIDIA Tesla V100 datasheet, March 2018](https://images.nvidia.com/content/technologies/volta/pdf/tesla-volta-v100-datasheet-letter-fnl-web.pdf),
  таблица Specifications на первой странице, отдельные колонки PCIe и SXM2.
- [Описание датасета авторами](https://github.com/at-aaims/summit_power_and_thermal_data),
  Node power, GPU/CPU power and temperatures: семантика переменных.
- [NVIDIA SMI documentation](https://docs.nvidia.com/deploy/nvidia-smi/index.html),
  Power Management, temperature thresholds: различие power cap, измерения и
  аппаратных температурных порогов. Современные режимы усреднения новых GPU
  не переносятся автоматически на V100/BMC 2022 года.

## Таблица

| Component | Model | Parameter | Value | Unit | Limit type | F18 mapping | Provenance | Applicability | Verification |
|---|---|---|---|---|---|---|---|---|---|
| Node | IBM AC922 compute | CPU/GPU count | 2 / 6 | devices | Configuration | 2 CPU, 6 GPU channels | OLCF Nodes; IBM slide 2 | Применимо к структуре F18 | FACT для Summit; FRU выбранных хостов unknown |
| GPU | Tesla V100 SXM2 | Published maximum board power | 300 | W | Datasheet maximum; не доказанный предел каждого отсчёта | gpu0_power…gpu5_power | NVIDIA Specifications; IBM slide 2 | Ограниченно: нужен установленный cap и семантика датчика | FACT спецификации; sensor-bound UNVERIFIED |
| GPU | Tesla V100 PCIe | Published maximum board power | 250 | W | Другая модификация | Нет подтверждённой привязки | NVIDIA Specifications | Неприменимо как порог SXM2 | FACT; не переносить на Summit |
| GPU | V100 Summit standard / high-memory | HBM2 capacity | 16 / 32 | GB per GPU | Capacity | Нет memory-usage в F18 | OLCF GPUs | Невозможно по F18; точный SKU a01–a16 unknown | FACT конфигураций, UNVERIFIED inventory |
| GPU | Installed V100 | Configured power cap, transient tolerance | unknown | W, s | Firmware/configuration | gpu*_power | Требуется NVML/BMC inventory 2022 | Пока невозможно | UNVERIFIED |
| GPU | Installed V100 | Thermal slowdown / shutdown / alarm thresholds | unknown | °C | Разные пороги контроллера | gpu*_core_temp | Требуется sensor/firmware table | Пока невозможно | UNVERIFIED |
| CPU | IBM POWER9 Summit compute | Active cores | 22 per CPU | cores | Configuration | cpu*_temp_mean агрегирует ядра | OLCF Nodes; IBM slide 4 | Ограниченно: состава sensor mean не определяет | FACT |
| CPU | Exact installed POWER9 SKU | TDP / package electrical or thermal hard bound | unknown | W / °C | TDP и hard limit различны | cpu0_power, cpu1_power; cpu*_temp_mean | OLCF не задаёт sensor-bound | Пока невозможно | UNVERIFIED |
| PSU | AC922 six-GPU design, FRU unknown | Rated supply capacity, two supplies | 2200 each; 2 units | W | Supply rating, не AC-input alarm | psu0_power, psu1_power | IBM slide 2 | Ограниченно; нужны DC rating conditions/efficiency/sharing | FACT design rating; точный FRU UNVERIFIED |
| PSU | Same design | Supported input options | 200 AC / 277 AC / 400 DC | V | Design input options | Нет voltage в F18 | IBM slide 2 | Не задаёт input-power threshold; фактический ввод unknown | FACT design; UNVERIFIED installation |
| PSU | Installed supply + firmware | AC input upper alarm and efficiency curve | unknown | W / fraction | Sensor limit / conversion | psu*_power (raw: ps*_input_power) | Нужны FRU specification и BMC SDR | Пока невозможно | UNVERIFIED |

Полные названия F18 задаются `internal/modules/telemetry/domain/record.go`
(`FeatureNames`) и mapping ETL.
Обозначения gpu*/cpu*/psu* здесь относятся к нормализованным именам проекта:
температуры CPU — cpu0_mean_temp/cpu1_mean_temp. Raw ps*_input_power отображается
в psu*_power; raw p0_gpu[0..2]/p1_gpu[0..2]_power — в gpu[0..5]_power.

## Сопоставимость

По описанию авторов датасета PSU-каналы измеряют входную AC-мощность,
CPU/GPU — DC-потребление компонентов. Это разные границы измерения.
`P_AC = P_DC / efficiency` допустимо только для согласованных времён и всех
нагрузок конкретного PSU; F18 не даёт efficiency, load sharing и всей DC-нагрузки.
Сумма CPU/GPU также не равна всей DC-мощности узла. Поэтому сравнение AC input
с 2200 W или суммы двух входов с 4400 W как строгой сигнализацией необоснованно.

GPU board-power specification / power management cap / TDP / измеренная
мощность не являются взаимозаменяемыми. Близость к 300 W может быть штатной
работой ограничителя. Даже превышение требует проверки датчика, averaging,
погрешности, времени и действительного SKU/cap; оно само по себе не доказывает
аппаратный дефект. CPU package power нельзя сравнить с непроверенным TDP.
Средняя температура CPU может быть ниже порога при перегреве одного ядра;
максимальная температура ядра в F18 отсутствует. GPU memory temperature также
не входит в F18. Наименование «паспортный предел» не заменяет BMC alarm table.

## Реализуемость и необходимые сведения

INFERENCE: сейчас обоснован **контекст оборудования**, но не полный бинарный Y.
Для температуры CPU и PSU строгий проверенный предел отсутствует; для GPU
известна опубликованная мощность модификации, но нет достаточной привязки к
измерению. В основном протоколе Y=`unknown`, отдельные неприменимые параметры
имеют `not_applicable`. Нулевую вероятность срабатывания или полезную частоту
Y по этим сведениям вычислить нельзя. Power/thermal control и 10-секундное
усреднение могут сделать допустимый hard-bound сигнал редким и скрыть пики.

После получения правильного sensor-bound превышение означает несоответствие
измеренного параметра подтверждённому пределу, включая возможную ошибку датчика;
причина требует независимых логов. Такой сигнал потенциально отличает физически
недопустимое, но статистически привычное состояние. Его дополнительная ценность
относительно R/B пока UNVERIFIED. Групповой Y предлагается при подтверждённом
превышении минимум на двух различных хостах, с трёхзначной логикой доступности;
точная формула дана в [математической спецификации](group-detection-mathematical-spec.md).

Нужны: inventory hostname→SKU/FRU, установленный GPU cap, CPU power definition,
PSU efficiency и DC rating conditions, BMC SDR/firmware thresholds с 2022 года,
единицы/погрешности/aggregation каждого сенсора и независимые hardware logs.
Необходимо согласовать, можно ли продолжить исследование в режиме R+B при Y
unknown. Формальный третий голос и проценты отклонения от номинала не вводятся.
