# Реестр оборудования Summit — контрольная точка №1

Дата: 18.10.2026. Реестр исследования; утверждённых бинарных sensor bounds **0**.
Машиночитаемый оригинал: [summit-hardware-reference.json](../configs/summit-hardware-reference.json).
Пустое значение — `null` / unknown, а не ноль. `y_applicable=false` запрещает
использовать запись как положительный или отрицательный тест Y.

Подтверждение типовой конфигурации Summit отделено от подтверждения конкретного
hostname. В D1 для каждого выбранного хоста наблюдаются 2 CPU power, 6 GPU power
и 2 PSU AC канала. Это не удостоверяет SKU/FRU, ёмкость памяти или установленные caps.
CPU — IBM POWER9 SMT4 с 22 активными ядрами в типовом compute node; GPU — V100 SXM2.
8335-GTW и FSF069 ниже — кандидаты/сравнительные изделия, а не выдуманный host inventory.
GTH/GTX и GTG/GTW — разные варианты AC922; их частоты и feature codes не смешиваются.

## Нормализованные характеристики

Источники S-ID раскрыты ниже с разделами. Confidence:
confirmed_typical = подтверждено для типовой конфигурации;
confirmed_other_model/unit = подтверждено для другого изделия;
assumed = предположение; unknown = не установлено.
Совместимость structural_match не означает совместимость с бинарным пределом.

| ID | Тип / производитель | Точная модель / статус | Характеристика | Значение | Единица | Тип ограничения | Условия | F18 | Совместимость | Источник | Достоверность | Y |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| node.compute | node / IBM | Power System AC922; per-host MTM unknown | CPU/GPU count | 2 / 6 | devices | configuration | Summit compute; login nodes have 2x16-core + 4 GPUs | F18 structure | structural_match | olcf | confirmed_typical | нет |
| cpu.cores | CPU / IBM | POWER9 SMT4 22 active cores; per-host SKU unknown | active cores | 22 | cores | configuration | Compute nodes, not login nodes | cpu[0-1]_mean_temp | aggregation_not_a_limit | olcf, ibm_training | confirmed_typical | нет |
| cpu.gtw-clock | CPU / IBM | AC922 8335-GTW 22-core POWER9 (candidate) | base/turbo frequency | 2.78 / 3.07 | GHz | nominal | GTW product option; not independently bound to 288 hosts | — | not_applicable | ibm_gtw, leconte | assumed | нет |
| cpu.gtx-clock | CPU / IBM | AC922 8335-GTX EP0S (alternative product) | base/turbo frequency | 2.8 / 3.1 | GHz | nominal | Different product generation; not evidence for Summit SKU | — | not_applicable | ibm_gth | confirmed_other_model | нет |
| cpu.tdp | CPU / IBM | Installed POWER9 SKU unknown | published TDP | unknown | W | unknown | No verified installed-SKU/sensor bound; source mean temperature cannot certify individual-core maximum | cpu[0-1]_power | unknown | olcf, ibm_gtw | unknown | нет |
| cpu.electrical | CPU / IBM | Installed POWER9 SKU unknown | package electrical limit | unknown | W | unknown | No verified installed-SKU/sensor bound; source mean temperature cannot certify individual-core maximum | cpu[0-1]_power | unknown | olcf, ibm_gtw | unknown | нет |
| cpu.operating | CPU / IBM | Installed POWER9 SKU unknown | core operating temperature | unknown | degC | unknown | No verified installed-SKU/sensor bound; source mean temperature cannot certify individual-core maximum | cpu[0-1]_mean_temp | unknown | olcf, ibm_gtw | unknown | нет |
| cpu.slowdown | CPU / IBM | Installed POWER9 SKU unknown | thermal throttling threshold | unknown | degC | unknown | No verified installed-SKU/sensor bound; source mean temperature cannot certify individual-core maximum | cpu[0-1]_mean_temp | unknown | olcf, ibm_gtw | unknown | нет |
| cpu.shutdown | CPU / IBM | Installed POWER9 SKU unknown | thermal shutdown threshold | unknown | degC | unknown | No verified installed-SKU/sensor bound; source mean temperature cannot certify individual-core maximum | cpu[0-1]_mean_temp | unknown | olcf, ibm_gtw | unknown | нет |
| cpu.other-190 | CPU / IBM | 8335-GTG EP0K / EP0M, 16/20-core | processor feature power | 190 | W | nominal | REDP5472 table 2-2; other CPUs, not Summit 22-core | cpu[0-1]_power | not_applicable | ibm_gtw | confirmed_other_model | нет |
| gpu.board | GPU / NVIDIA | Tesla V100 SXM2 16/32GB; installed P/N unknown | published board power | 300 | W | published_board_power | Not installed cap, tolerance, BMC alarm or per-sample hard bound | gpu[0-5]_power | unknown | v100, ibm_training | confirmed_typical | нет |
| gpu.hbm | GPU / NVIDIA | Tesla V100 SXM2 | memory capacity options | 16 / 32 | GB | capacity | OLCF standard/high-memory variants; no hostname inventory | — | not_applicable | v100, olcf | confirmed_typical | нет |
| gpu.tdp | GPU / NVIDIA | Installed V100 SXM2 SKU/firmware unknown | separately specified TDP | unknown | W | unknown | Query installed GPU/firmware; PCIe numbers and another system cap cannot be transferred | gpu[0-5]_power | unknown | smi, v100 | unknown | нет |
| gpu.cap | GPU / NVIDIA | Installed V100 SXM2 SKU/firmware unknown | installed power limit | unknown | W | unknown | Query installed GPU/firmware; PCIe numbers and another system cap cannot be transferred | gpu[0-5]_power | unknown | smi, v100 | unknown | нет |
| gpu.max-cap | GPU / NVIDIA | Installed V100 SXM2 SKU/firmware unknown | maximum configurable power limit | unknown | W | unknown | Query installed GPU/firmware; PCIe numbers and another system cap cannot be transferred | gpu[0-5]_power | unknown | smi, v100 | unknown | нет |
| gpu.min-cap | GPU / NVIDIA | Installed V100 SXM2 SKU/firmware unknown | minimum configurable power limit | unknown | W | unknown | Query installed GPU/firmware; PCIe numbers and another system cap cannot be transferred | gpu[0-5]_power | unknown | smi, v100 | unknown | нет |
| gpu.operating | GPU / NVIDIA | Installed V100 SXM2 SKU/firmware unknown | maximum operating GPU core temperature | unknown | degC | unknown | Query installed GPU/firmware; PCIe numbers and another system cap cannot be transferred | gpu[0-5]_core_temp | unknown | smi, v100 | unknown | нет |
| gpu.slowdown | GPU / NVIDIA | Installed V100 SXM2 SKU/firmware unknown | thermal slowdown threshold | unknown | degC | unknown | Query installed GPU/firmware; PCIe numbers and another system cap cannot be transferred | gpu[0-5]_core_temp | unknown | smi, v100 | unknown | нет |
| gpu.shutdown | GPU / NVIDIA | Installed V100 SXM2 SKU/firmware unknown | thermal shutdown threshold | unknown | degC | unknown | Query installed GPU/firmware; PCIe numbers and another system cap cannot be transferred | gpu[0-5]_core_temp | unknown | smi, v100 | unknown | нет |
| pcie.board | GPU / NVIDIA | Tesla V100 PCIe (not Summit SXM2) | board power | 250 | W | other_model_limit | PCIe Product Brief Table 5; NOT a SXM2 bound | gpu[0-5]_power | not_applicable | v100_pcie | confirmed_other_model | нет |
| pcie.qualification | GPU / NVIDIA | Tesla V100 PCIe (not Summit SXM2) | thermal qualification temperature | 80 | degC | other_model_limit | PCIe Product Brief Table 5; NOT a SXM2 bound | gpu[0-5]_core_temp | not_applicable | v100_pcie | confirmed_other_model | нет |
| pcie.operating | GPU / NVIDIA | Tesla V100 PCIe (not Summit SXM2) | maximum GPU operating temperature | 83 | degC | other_model_limit | PCIe Product Brief Table 5; NOT a SXM2 bound | gpu[0-5]_core_temp | not_applicable | v100_pcie | confirmed_other_model | нет |
| pcie.hbm | GPU / NVIDIA | Tesla V100 PCIe (not Summit SXM2) | maximum HBM operating temperature | 85 | degC | other_model_limit | PCIe Product Brief Table 5; NOT a SXM2 bound | gpu[0-5]_core_temp | not_applicable | v100_pcie | confirmed_other_model | нет |
| pcie.slowdown | GPU / NVIDIA | Tesla V100 PCIe (not Summit SXM2) | 50% clock slowdown temperature | 87 | degC | other_model_limit | PCIe Product Brief Table 5; NOT a SXM2 bound | gpu[0-5]_core_temp | not_applicable | v100_pcie | confirmed_other_model | нет |
| pcie.shutdown | GPU / NVIDIA | Tesla V100 PCIe (not Summit SXM2) | GPU shutdown temperature | 90 | degC | other_model_limit | PCIe Product Brief Table 5; NOT a SXM2 bound | gpu[0-5]_core_temp | not_applicable | v100_pcie | confirmed_other_model | нет |
| psu.design | PSU / IBM; OEM unknown for installed hosts | AC922 design; FRU unknown | rated supply power | 2200 | W | rated_DC_output | Two supplies; redundancy may throttle six-GPU load on failure; AC sensor is different boundary | psu[0-1]_power | incompatible_measurement_boundary | ibm_training, ibm_gtw | confirmed_typical | нет |
| psu.input-options | PSU / IBM | AC922 six-GPU design | supported input options | 200 VAC / 277 VAC / 400 VDC | V | design_options | Not evidence of installed feed voltage | — | not_applicable | ibm_training | confirmed_typical | нет |
| psu.fsf069 | PSU / IBM (certificate); AcBel attribution not host-verified | FSF069 (candidate only) | rated DC output | 2200 | W | rated_DC_output | Tested serial 11S01KL779YL10A075B10C; not 288-host inventory | psu[0-1]_power | incompatible_measurement_boundary | psu_test | confirmed_other_unit | нет |
| psu.voltage | PSU / IBM (certificate) | FSF069 (candidate only) | rated input voltage | 200 / 277 | VAC | rated_range | Candidate not linked to hosts; test at 230 V 60 Hz | — | not_applicable | psu_test | confirmed_other_unit | нет |
| psu.current | PSU / IBM (certificate) | FSF069 (candidate only) | rated input current | 12 | A | rated_current | V*I is apparent power; needs PF; not a measured W alarm | — | not_applicable | psu_test | confirmed_other_unit | нет |
| psu.output-voltage | PSU / IBM (certificate) | FSF069 (candidate only) | measured main/standby output voltage at full load | 12.23 / 12.12 | VDC | test_measurement | At 230 V 60 Hz; not rated tolerance or installed sensor threshold | — | not_applicable | psu_test | confirmed_other_unit | нет |
| psu.efficiency | PSU / IBM (certificate) | FSF069 (candidate only) | efficiency at 50% / full load | 95.11 / 92.62 | percent | test_measurement | 230 V 60 Hz; excludes fan power; not universal efficiency | psu[0-1]_power | unknown | psu_test | confirmed_other_unit | нет |
| psu.full-ac | PSU / IBM (certificate) | FSF069 (candidate only) | measured full-load AC input | 2386 | W | test_measurement | For 2210 W measured DC output; illustrates AC > DC rating; NOT an upper bound | psu[0-1]_power | unknown | psu_test | confirmed_other_unit | нет |
| psu.alarm | PSU / unknown | Installed FRU/firmware unknown | installed AC input BMC alarm | unknown | W | unknown | Not supplied by F18, raw schema or verified host inventory | psu[0-1]_power | unknown | original | unknown | нет |
| psu.thermal | PSU / unknown | Installed FRU/firmware unknown | installed PSU thermal alarm | unknown | degC | unknown | Not supplied by F18, raw schema or verified host inventory | psu[0-1]_power | unknown | original | unknown | нет |
| psu.sharing | PSU / unknown | Installed FRU/firmware unknown | installed load-sharing rule | unknown | fraction | unknown | Not supplied by F18, raw schema or verified host inventory | psu[0-1]_power | unknown | original | unknown | нет |
| node.ambient | node / IBM | AC922 GTH table 3-1 (not host-bound) | allowable inlet dry-bulb temperature | 5 / 40 | degC | environmental | Not CPU or GPU junction temperature; altitude derating applies | — | not_applicable | ibm_gth | confirmed_other_model | нет |

## Источники

- **olcf**: [источник](https://docs.olcf.ornl.gov/systems/summit_user_guide.html), Summit Nodes; Node Types; GPUs.
- **ibm_training**: [источник](https://www.olcf.ornl.gov/wp-content/uploads/2018/12/summit_workshop_thompto.pdf), POWER AC922 Design — 6 GPU, PDF p.2; POWER9 Common Features, PDF p.4.
- **ibm_gtw**: [источник](https://www.redbooks.ibm.com/redpapers/pdfs/redp5472.pdf), 1.2.2, PDF pp.17–18; 3.3 System power, PDF pp.53–54 (1-based).
- **ibm_gth**: [источник](https://www.redbooks.ibm.com/redpapers/pdfs/redp5494.pdf), 2.2.4 table 2-2, PDF p.31; 3.1 table 3-1 PDF pp.58–59; 3.3 PDF p.61.
- **v100**: [источник](https://images.nvidia.com/content/pdf/vgpu/data-sheet/nvidia-v100.pdf), Specifications, PDF p.1, May 2018.
- **v100_pcie**: [источник](https://images.nvidia.com/content/tesla/pdf/Tesla-V100-PCIe-Product-Brief.pdf), Table 5 Board Power and Thermal Specifications, PDF p.9.
- **smi**: [источник](https://docs.nvidia.com/deploy/nvidia-smi/index.html), GPU Temperature; GPU Power Readings; Min/Max Power Limit; --power-limit.
- **original**: [источник](https://github.com/at-aaims/summit_power_and_thermal_data), DATA-SPECIFIC INFORMATION / Sample information; Node power; CPU/GPU power and temperature; METHODOLOGICAL INFORMATION.
- **clusterwise**: [источник](https://huggingface.co/datasets/MachaParfait/ClusterWise/blob/main/README.md), Data Fields; hostname format, node_state, label, xid; card revision 93fb62c.
- **leconte**: [источник](https://docs.excl.ornl.gov/system-overview/leconte), Description; GPU Performance (analogous machine, not Summit host inventory).
- **psu_test**: [источник](https://www.clearesult.com/80plus/sites/80plus/files/manufacturer-certificate/ibm-fsf069-3229.pdf), Rated Specifications; Loading and Efficiency, PDF p.1, test date 2017-06-01.

## Таблица 288 хостов

T = ссылка `summit_compute_typical` в JSON: типовая AC922, 2×POWER9, 6×V100 SXM2,
2×2200 W design; это **не** индивидуально подтверждённая комплектация.
H = подтверждены только каналы F18 конкретного хоста в D1.
U = неизвестно: installed SKU/FRU, standard/high-memory, caps и sensor bounds.
Положение L расшифровано по явной схеме авторов ClusterWise (Data Fields) и
первичного датасета (Sample information). Это документированное расположение
в системе имён; независимой актуальной сверки facility inventory нет.
Стойка/позиция не удостоверяет общий PDU, ветвь электропитания, cooling loop,
IB switch, метрические расстояния и физическую причину совпадений.

| Hostname | Группа / кабинет L | Колонка | Ряд | Позиция снизу | F18 | Типовая конфигурация | SKU/FRU | High-memory | Bounds Y |
|---|---|---|---|---|---|---|---|---|---|
| a01n01 | a01 | a | 1 | 1 | H | T | U | U | U |
| a01n02 | a01 | a | 1 | 2 | H | T | U | U | U |
| a01n03 | a01 | a | 1 | 3 | H | T | U | U | U |
| a01n04 | a01 | a | 1 | 4 | H | T | U | U | U |
| a01n05 | a01 | a | 1 | 5 | H | T | U | U | U |
| a01n06 | a01 | a | 1 | 6 | H | T | U | U | U |
| a01n07 | a01 | a | 1 | 7 | H | T | U | U | U |
| a01n08 | a01 | a | 1 | 8 | H | T | U | U | U |
| a01n09 | a01 | a | 1 | 9 | H | T | U | U | U |
| a01n10 | a01 | a | 1 | 10 | H | T | U | U | U |
| a01n11 | a01 | a | 1 | 11 | H | T | U | U | U |
| a01n12 | a01 | a | 1 | 12 | H | T | U | U | U |
| a01n13 | a01 | a | 1 | 13 | H | T | U | U | U |
| a01n14 | a01 | a | 1 | 14 | H | T | U | U | U |
| a01n15 | a01 | a | 1 | 15 | H | T | U | U | U |
| a01n16 | a01 | a | 1 | 16 | H | T | U | U | U |
| a01n17 | a01 | a | 1 | 17 | H | T | U | U | U |
| a01n18 | a01 | a | 1 | 18 | H | T | U | U | U |
| a02n01 | a02 | a | 2 | 1 | H | T | U | U | U |
| a02n02 | a02 | a | 2 | 2 | H | T | U | U | U |
| a02n03 | a02 | a | 2 | 3 | H | T | U | U | U |
| a02n04 | a02 | a | 2 | 4 | H | T | U | U | U |
| a02n05 | a02 | a | 2 | 5 | H | T | U | U | U |
| a02n06 | a02 | a | 2 | 6 | H | T | U | U | U |
| a02n07 | a02 | a | 2 | 7 | H | T | U | U | U |
| a02n08 | a02 | a | 2 | 8 | H | T | U | U | U |
| a02n09 | a02 | a | 2 | 9 | H | T | U | U | U |
| a02n10 | a02 | a | 2 | 10 | H | T | U | U | U |
| a02n11 | a02 | a | 2 | 11 | H | T | U | U | U |
| a02n12 | a02 | a | 2 | 12 | H | T | U | U | U |
| a02n13 | a02 | a | 2 | 13 | H | T | U | U | U |
| a02n14 | a02 | a | 2 | 14 | H | T | U | U | U |
| a02n15 | a02 | a | 2 | 15 | H | T | U | U | U |
| a02n16 | a02 | a | 2 | 16 | H | T | U | U | U |
| a02n17 | a02 | a | 2 | 17 | H | T | U | U | U |
| a02n18 | a02 | a | 2 | 18 | H | T | U | U | U |
| a03n01 | a03 | a | 3 | 1 | H | T | U | U | U |
| a03n02 | a03 | a | 3 | 2 | H | T | U | U | U |
| a03n03 | a03 | a | 3 | 3 | H | T | U | U | U |
| a03n04 | a03 | a | 3 | 4 | H | T | U | U | U |
| a03n05 | a03 | a | 3 | 5 | H | T | U | U | U |
| a03n06 | a03 | a | 3 | 6 | H | T | U | U | U |
| a03n07 | a03 | a | 3 | 7 | H | T | U | U | U |
| a03n08 | a03 | a | 3 | 8 | H | T | U | U | U |
| a03n09 | a03 | a | 3 | 9 | H | T | U | U | U |
| a03n10 | a03 | a | 3 | 10 | H | T | U | U | U |
| a03n11 | a03 | a | 3 | 11 | H | T | U | U | U |
| a03n12 | a03 | a | 3 | 12 | H | T | U | U | U |
| a03n13 | a03 | a | 3 | 13 | H | T | U | U | U |
| a03n14 | a03 | a | 3 | 14 | H | T | U | U | U |
| a03n15 | a03 | a | 3 | 15 | H | T | U | U | U |
| a03n16 | a03 | a | 3 | 16 | H | T | U | U | U |
| a03n17 | a03 | a | 3 | 17 | H | T | U | U | U |
| a03n18 | a03 | a | 3 | 18 | H | T | U | U | U |
| a04n01 | a04 | a | 4 | 1 | H | T | U | U | U |
| a04n02 | a04 | a | 4 | 2 | H | T | U | U | U |
| a04n03 | a04 | a | 4 | 3 | H | T | U | U | U |
| a04n04 | a04 | a | 4 | 4 | H | T | U | U | U |
| a04n05 | a04 | a | 4 | 5 | H | T | U | U | U |
| a04n06 | a04 | a | 4 | 6 | H | T | U | U | U |
| a04n07 | a04 | a | 4 | 7 | H | T | U | U | U |
| a04n08 | a04 | a | 4 | 8 | H | T | U | U | U |
| a04n09 | a04 | a | 4 | 9 | H | T | U | U | U |
| a04n10 | a04 | a | 4 | 10 | H | T | U | U | U |
| a04n11 | a04 | a | 4 | 11 | H | T | U | U | U |
| a04n12 | a04 | a | 4 | 12 | H | T | U | U | U |
| a04n13 | a04 | a | 4 | 13 | H | T | U | U | U |
| a04n14 | a04 | a | 4 | 14 | H | T | U | U | U |
| a04n15 | a04 | a | 4 | 15 | H | T | U | U | U |
| a04n16 | a04 | a | 4 | 16 | H | T | U | U | U |
| a04n17 | a04 | a | 4 | 17 | H | T | U | U | U |
| a04n18 | a04 | a | 4 | 18 | H | T | U | U | U |
| a05n01 | a05 | a | 5 | 1 | H | T | U | U | U |
| a05n02 | a05 | a | 5 | 2 | H | T | U | U | U |
| a05n03 | a05 | a | 5 | 3 | H | T | U | U | U |
| a05n04 | a05 | a | 5 | 4 | H | T | U | U | U |
| a05n05 | a05 | a | 5 | 5 | H | T | U | U | U |
| a05n06 | a05 | a | 5 | 6 | H | T | U | U | U |
| a05n07 | a05 | a | 5 | 7 | H | T | U | U | U |
| a05n08 | a05 | a | 5 | 8 | H | T | U | U | U |
| a05n09 | a05 | a | 5 | 9 | H | T | U | U | U |
| a05n10 | a05 | a | 5 | 10 | H | T | U | U | U |
| a05n11 | a05 | a | 5 | 11 | H | T | U | U | U |
| a05n12 | a05 | a | 5 | 12 | H | T | U | U | U |
| a05n13 | a05 | a | 5 | 13 | H | T | U | U | U |
| a05n14 | a05 | a | 5 | 14 | H | T | U | U | U |
| a05n15 | a05 | a | 5 | 15 | H | T | U | U | U |
| a05n16 | a05 | a | 5 | 16 | H | T | U | U | U |
| a05n17 | a05 | a | 5 | 17 | H | T | U | U | U |
| a05n18 | a05 | a | 5 | 18 | H | T | U | U | U |
| a06n01 | a06 | a | 6 | 1 | H | T | U | U | U |
| a06n02 | a06 | a | 6 | 2 | H | T | U | U | U |
| a06n03 | a06 | a | 6 | 3 | H | T | U | U | U |
| a06n04 | a06 | a | 6 | 4 | H | T | U | U | U |
| a06n05 | a06 | a | 6 | 5 | H | T | U | U | U |
| a06n06 | a06 | a | 6 | 6 | H | T | U | U | U |
| a06n07 | a06 | a | 6 | 7 | H | T | U | U | U |
| a06n08 | a06 | a | 6 | 8 | H | T | U | U | U |
| a06n09 | a06 | a | 6 | 9 | H | T | U | U | U |
| a06n10 | a06 | a | 6 | 10 | H | T | U | U | U |
| a06n11 | a06 | a | 6 | 11 | H | T | U | U | U |
| a06n12 | a06 | a | 6 | 12 | H | T | U | U | U |
| a06n13 | a06 | a | 6 | 13 | H | T | U | U | U |
| a06n14 | a06 | a | 6 | 14 | H | T | U | U | U |
| a06n15 | a06 | a | 6 | 15 | H | T | U | U | U |
| a06n16 | a06 | a | 6 | 16 | H | T | U | U | U |
| a06n17 | a06 | a | 6 | 17 | H | T | U | U | U |
| a06n18 | a06 | a | 6 | 18 | H | T | U | U | U |
| a07n01 | a07 | a | 7 | 1 | H | T | U | U | U |
| a07n02 | a07 | a | 7 | 2 | H | T | U | U | U |
| a07n03 | a07 | a | 7 | 3 | H | T | U | U | U |
| a07n04 | a07 | a | 7 | 4 | H | T | U | U | U |
| a07n05 | a07 | a | 7 | 5 | H | T | U | U | U |
| a07n06 | a07 | a | 7 | 6 | H | T | U | U | U |
| a07n07 | a07 | a | 7 | 7 | H | T | U | U | U |
| a07n08 | a07 | a | 7 | 8 | H | T | U | U | U |
| a07n09 | a07 | a | 7 | 9 | H | T | U | U | U |
| a07n10 | a07 | a | 7 | 10 | H | T | U | U | U |
| a07n11 | a07 | a | 7 | 11 | H | T | U | U | U |
| a07n12 | a07 | a | 7 | 12 | H | T | U | U | U |
| a07n13 | a07 | a | 7 | 13 | H | T | U | U | U |
| a07n14 | a07 | a | 7 | 14 | H | T | U | U | U |
| a07n15 | a07 | a | 7 | 15 | H | T | U | U | U |
| a07n16 | a07 | a | 7 | 16 | H | T | U | U | U |
| a07n17 | a07 | a | 7 | 17 | H | T | U | U | U |
| a07n18 | a07 | a | 7 | 18 | H | T | U | U | U |
| a08n01 | a08 | a | 8 | 1 | H | T | U | U | U |
| a08n02 | a08 | a | 8 | 2 | H | T | U | U | U |
| a08n03 | a08 | a | 8 | 3 | H | T | U | U | U |
| a08n04 | a08 | a | 8 | 4 | H | T | U | U | U |
| a08n05 | a08 | a | 8 | 5 | H | T | U | U | U |
| a08n06 | a08 | a | 8 | 6 | H | T | U | U | U |
| a08n07 | a08 | a | 8 | 7 | H | T | U | U | U |
| a08n08 | a08 | a | 8 | 8 | H | T | U | U | U |
| a08n09 | a08 | a | 8 | 9 | H | T | U | U | U |
| a08n10 | a08 | a | 8 | 10 | H | T | U | U | U |
| a08n11 | a08 | a | 8 | 11 | H | T | U | U | U |
| a08n12 | a08 | a | 8 | 12 | H | T | U | U | U |
| a08n13 | a08 | a | 8 | 13 | H | T | U | U | U |
| a08n14 | a08 | a | 8 | 14 | H | T | U | U | U |
| a08n15 | a08 | a | 8 | 15 | H | T | U | U | U |
| a08n16 | a08 | a | 8 | 16 | H | T | U | U | U |
| a08n17 | a08 | a | 8 | 17 | H | T | U | U | U |
| a08n18 | a08 | a | 8 | 18 | H | T | U | U | U |
| a09n01 | a09 | a | 9 | 1 | H | T | U | U | U |
| a09n02 | a09 | a | 9 | 2 | H | T | U | U | U |
| a09n03 | a09 | a | 9 | 3 | H | T | U | U | U |
| a09n04 | a09 | a | 9 | 4 | H | T | U | U | U |
| a09n05 | a09 | a | 9 | 5 | H | T | U | U | U |
| a09n06 | a09 | a | 9 | 6 | H | T | U | U | U |
| a09n07 | a09 | a | 9 | 7 | H | T | U | U | U |
| a09n08 | a09 | a | 9 | 8 | H | T | U | U | U |
| a09n09 | a09 | a | 9 | 9 | H | T | U | U | U |
| a09n10 | a09 | a | 9 | 10 | H | T | U | U | U |
| a09n11 | a09 | a | 9 | 11 | H | T | U | U | U |
| a09n12 | a09 | a | 9 | 12 | H | T | U | U | U |
| a09n13 | a09 | a | 9 | 13 | H | T | U | U | U |
| a09n14 | a09 | a | 9 | 14 | H | T | U | U | U |
| a09n15 | a09 | a | 9 | 15 | H | T | U | U | U |
| a09n16 | a09 | a | 9 | 16 | H | T | U | U | U |
| a09n17 | a09 | a | 9 | 17 | H | T | U | U | U |
| a09n18 | a09 | a | 9 | 18 | H | T | U | U | U |
| a10n01 | a10 | a | 10 | 1 | H | T | U | U | U |
| a10n02 | a10 | a | 10 | 2 | H | T | U | U | U |
| a10n03 | a10 | a | 10 | 3 | H | T | U | U | U |
| a10n04 | a10 | a | 10 | 4 | H | T | U | U | U |
| a10n05 | a10 | a | 10 | 5 | H | T | U | U | U |
| a10n06 | a10 | a | 10 | 6 | H | T | U | U | U |
| a10n07 | a10 | a | 10 | 7 | H | T | U | U | U |
| a10n08 | a10 | a | 10 | 8 | H | T | U | U | U |
| a10n09 | a10 | a | 10 | 9 | H | T | U | U | U |
| a10n10 | a10 | a | 10 | 10 | H | T | U | U | U |
| a10n11 | a10 | a | 10 | 11 | H | T | U | U | U |
| a10n12 | a10 | a | 10 | 12 | H | T | U | U | U |
| a10n13 | a10 | a | 10 | 13 | H | T | U | U | U |
| a10n14 | a10 | a | 10 | 14 | H | T | U | U | U |
| a10n15 | a10 | a | 10 | 15 | H | T | U | U | U |
| a10n16 | a10 | a | 10 | 16 | H | T | U | U | U |
| a10n17 | a10 | a | 10 | 17 | H | T | U | U | U |
| a10n18 | a10 | a | 10 | 18 | H | T | U | U | U |
| a11n01 | a11 | a | 11 | 1 | H | T | U | U | U |
| a11n02 | a11 | a | 11 | 2 | H | T | U | U | U |
| a11n03 | a11 | a | 11 | 3 | H | T | U | U | U |
| a11n04 | a11 | a | 11 | 4 | H | T | U | U | U |
| a11n05 | a11 | a | 11 | 5 | H | T | U | U | U |
| a11n06 | a11 | a | 11 | 6 | H | T | U | U | U |
| a11n07 | a11 | a | 11 | 7 | H | T | U | U | U |
| a11n08 | a11 | a | 11 | 8 | H | T | U | U | U |
| a11n09 | a11 | a | 11 | 9 | H | T | U | U | U |
| a11n10 | a11 | a | 11 | 10 | H | T | U | U | U |
| a11n11 | a11 | a | 11 | 11 | H | T | U | U | U |
| a11n12 | a11 | a | 11 | 12 | H | T | U | U | U |
| a11n13 | a11 | a | 11 | 13 | H | T | U | U | U |
| a11n14 | a11 | a | 11 | 14 | H | T | U | U | U |
| a11n15 | a11 | a | 11 | 15 | H | T | U | U | U |
| a11n16 | a11 | a | 11 | 16 | H | T | U | U | U |
| a11n17 | a11 | a | 11 | 17 | H | T | U | U | U |
| a11n18 | a11 | a | 11 | 18 | H | T | U | U | U |
| a12n01 | a12 | a | 12 | 1 | H | T | U | U | U |
| a12n02 | a12 | a | 12 | 2 | H | T | U | U | U |
| a12n03 | a12 | a | 12 | 3 | H | T | U | U | U |
| a12n04 | a12 | a | 12 | 4 | H | T | U | U | U |
| a12n05 | a12 | a | 12 | 5 | H | T | U | U | U |
| a12n06 | a12 | a | 12 | 6 | H | T | U | U | U |
| a12n07 | a12 | a | 12 | 7 | H | T | U | U | U |
| a12n08 | a12 | a | 12 | 8 | H | T | U | U | U |
| a12n09 | a12 | a | 12 | 9 | H | T | U | U | U |
| a12n10 | a12 | a | 12 | 10 | H | T | U | U | U |
| a12n11 | a12 | a | 12 | 11 | H | T | U | U | U |
| a12n12 | a12 | a | 12 | 12 | H | T | U | U | U |
| a12n13 | a12 | a | 12 | 13 | H | T | U | U | U |
| a12n14 | a12 | a | 12 | 14 | H | T | U | U | U |
| a12n15 | a12 | a | 12 | 15 | H | T | U | U | U |
| a12n16 | a12 | a | 12 | 16 | H | T | U | U | U |
| a12n17 | a12 | a | 12 | 17 | H | T | U | U | U |
| a12n18 | a12 | a | 12 | 18 | H | T | U | U | U |
| a13n01 | a13 | a | 13 | 1 | H | T | U | U | U |
| a13n02 | a13 | a | 13 | 2 | H | T | U | U | U |
| a13n03 | a13 | a | 13 | 3 | H | T | U | U | U |
| a13n04 | a13 | a | 13 | 4 | H | T | U | U | U |
| a13n05 | a13 | a | 13 | 5 | H | T | U | U | U |
| a13n06 | a13 | a | 13 | 6 | H | T | U | U | U |
| a13n07 | a13 | a | 13 | 7 | H | T | U | U | U |
| a13n08 | a13 | a | 13 | 8 | H | T | U | U | U |
| a13n09 | a13 | a | 13 | 9 | H | T | U | U | U |
| a13n10 | a13 | a | 13 | 10 | H | T | U | U | U |
| a13n11 | a13 | a | 13 | 11 | H | T | U | U | U |
| a13n12 | a13 | a | 13 | 12 | H | T | U | U | U |
| a13n13 | a13 | a | 13 | 13 | H | T | U | U | U |
| a13n14 | a13 | a | 13 | 14 | H | T | U | U | U |
| a13n15 | a13 | a | 13 | 15 | H | T | U | U | U |
| a13n16 | a13 | a | 13 | 16 | H | T | U | U | U |
| a13n17 | a13 | a | 13 | 17 | H | T | U | U | U |
| a13n18 | a13 | a | 13 | 18 | H | T | U | U | U |
| a14n01 | a14 | a | 14 | 1 | H | T | U | U | U |
| a14n02 | a14 | a | 14 | 2 | H | T | U | U | U |
| a14n03 | a14 | a | 14 | 3 | H | T | U | U | U |
| a14n04 | a14 | a | 14 | 4 | H | T | U | U | U |
| a14n05 | a14 | a | 14 | 5 | H | T | U | U | U |
| a14n06 | a14 | a | 14 | 6 | H | T | U | U | U |
| a14n07 | a14 | a | 14 | 7 | H | T | U | U | U |
| a14n08 | a14 | a | 14 | 8 | H | T | U | U | U |
| a14n09 | a14 | a | 14 | 9 | H | T | U | U | U |
| a14n10 | a14 | a | 14 | 10 | H | T | U | U | U |
| a14n11 | a14 | a | 14 | 11 | H | T | U | U | U |
| a14n12 | a14 | a | 14 | 12 | H | T | U | U | U |
| a14n13 | a14 | a | 14 | 13 | H | T | U | U | U |
| a14n14 | a14 | a | 14 | 14 | H | T | U | U | U |
| a14n15 | a14 | a | 14 | 15 | H | T | U | U | U |
| a14n16 | a14 | a | 14 | 16 | H | T | U | U | U |
| a14n17 | a14 | a | 14 | 17 | H | T | U | U | U |
| a14n18 | a14 | a | 14 | 18 | H | T | U | U | U |
| a15n01 | a15 | a | 15 | 1 | H | T | U | U | U |
| a15n02 | a15 | a | 15 | 2 | H | T | U | U | U |
| a15n03 | a15 | a | 15 | 3 | H | T | U | U | U |
| a15n04 | a15 | a | 15 | 4 | H | T | U | U | U |
| a15n05 | a15 | a | 15 | 5 | H | T | U | U | U |
| a15n06 | a15 | a | 15 | 6 | H | T | U | U | U |
| a15n07 | a15 | a | 15 | 7 | H | T | U | U | U |
| a15n08 | a15 | a | 15 | 8 | H | T | U | U | U |
| a15n09 | a15 | a | 15 | 9 | H | T | U | U | U |
| a15n10 | a15 | a | 15 | 10 | H | T | U | U | U |
| a15n11 | a15 | a | 15 | 11 | H | T | U | U | U |
| a15n12 | a15 | a | 15 | 12 | H | T | U | U | U |
| a15n13 | a15 | a | 15 | 13 | H | T | U | U | U |
| a15n14 | a15 | a | 15 | 14 | H | T | U | U | U |
| a15n15 | a15 | a | 15 | 15 | H | T | U | U | U |
| a15n16 | a15 | a | 15 | 16 | H | T | U | U | U |
| a15n17 | a15 | a | 15 | 17 | H | T | U | U | U |
| a15n18 | a15 | a | 15 | 18 | H | T | U | U | U |
| a16n01 | a16 | a | 16 | 1 | H | T | U | U | U |
| a16n02 | a16 | a | 16 | 2 | H | T | U | U | U |
| a16n03 | a16 | a | 16 | 3 | H | T | U | U | U |
| a16n04 | a16 | a | 16 | 4 | H | T | U | U | U |
| a16n05 | a16 | a | 16 | 5 | H | T | U | U | U |
| a16n06 | a16 | a | 16 | 6 | H | T | U | U | U |
| a16n07 | a16 | a | 16 | 7 | H | T | U | U | U |
| a16n08 | a16 | a | 16 | 8 | H | T | U | U | U |
| a16n09 | a16 | a | 16 | 9 | H | T | U | U | U |
| a16n10 | a16 | a | 16 | 10 | H | T | U | U | U |
| a16n11 | a16 | a | 16 | 11 | H | T | U | U | U |
| a16n12 | a16 | a | 16 | 12 | H | T | U | U | U |
| a16n13 | a16 | a | 16 | 13 | H | T | U | U | U |
| a16n14 | a16 | a | 16 | 14 | H | T | U | U | U |
| a16n15 | a16 | a | 16 | 15 | H | T | U | U | U |
| a16n16 | a16 | a | 16 | 16 | H | T | U | U | U |
| a16n17 | a16 | a | 16 | 17 | H | T | U | U | U |
| a16n18 | a16 | a | 16 | 18 | H | T | U | U | U |

Для каждого hostname имеются отдельные строки в JSON `host_inventory` со
статусами и provenance. Выборка/порядок сверены с неизменным prepared manifest
скриптом `tools/groupdiagnostics/d1.py`. Ни одному хосту не приписан точный
CPU SKU, PSU FRU, memory variant или power limit по статистике его поведения.
