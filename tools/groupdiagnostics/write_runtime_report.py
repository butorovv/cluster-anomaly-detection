"""Render the technical/scientific report from saved frozen-runtime results."""
import argparse
import csv
import json
from pathlib import Path
import statistics


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts',type=Path,default=Path('docs/group-runtime-v1'));parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.artifacts
    analysis=json.loads((root/'d2/analysis.json').read_text(encoding='utf-8'))
    summary=json.loads((root/'d2/run-summary.json').read_text(encoding='utf-8'))
    performance=json.loads((root/'performance.json').read_text(encoding='utf-8'))
    full=json.loads((root/'performance-full.json').read_text(encoding='utf-8'))['rows'][0]
    events=json.loads((root/'d2/events.json').read_text(encoding='utf-8'))
    context=json.loads((root/'d2/context-analysis.json').read_text(encoding='utf-8'))
    r=analysis['raw_dependency'];selected=analysis['selected_event'];counts=summary['raw_counts']
    lines=['# Реальные результаты группового прототипа Summit D2','',
           '18.10.2026. Исполняемый исследовательский прототип `summit-group-research-v1` завершён. '
           'Это предварительное статистическое обнаружение, не диагностика подтверждённых аппаратных неисправностей. '
           'Решения разрешены новым ТЗ пользователя; согласование научным руководителем не заявляется.','',
           '## Входы и замораживание','',
           'База main после PR №9: `a55e1fafea8b2ef7256d03457e6a11145709d870`. '
           'R/B/Y, CLI, профиль и D1 parity зафиксированы **до первого D2** коммитом '
           '`ae0efb8`; `adb5205` закрепил LF для SHA-bound JSON. Первый D2 binary '
           'имеет VCS revision `adb5205ed1fec142db12e9dc11447c436588c76d`, modified=false. '
           'Профиль, floor, δ grid и пороги не изменялись после просмотра D2.','',
           f"Group profile SHA-256: `{analysis['profile_sha256']}`. "
           'Входные SHA prepared/manifest/statistical/IF/B1/hardware/contract до и после '
           'совпадают в [run-summary.json](group-runtime-v1/d2/run-summary.json). '
           'Защищённые исторические файлы дополнительно проверены отдельным manifest.','',
           '288 хостов, a01–a16 по 18, F18, 10 s. D1 `[00:00,08:00)`, '
           'D2 `[08:00,16:00)` 18.01.2022, UTC — прежнее неподтверждённое допущение. '
           'D3 не используется. Все 829440 host states и 46080 group ticks D2 полны. '
           'Аппаратное исследование контрольной точки не повторялось.','',
           '## Математика и регрессия','',
           'Go реализует пять физических каналов хоста и десять group mean/population-spread '
           'координат; temporal host median/MAD, second-largest по двум различным хостам '
           'одного канала/знака и strict D1 Q99. B: отдельный 10D профиль каждой группы, '
           'robust normalization, Welford ddof1, SVD cutoff 1e-12, full rank либо unknown. '
           'Существующий узловой Mahalanobis и локальный B1 не изменены.','',
           '[D1 parity](group-runtime-v1/d1-parity.json): vectors, host/group median/MAD/scale, '
           'covariance, normalized center и R score совпали точно; max pseudoinverse error '
           '5.12e-14, max D² error 1.27e-12. При заранее заданных rtol=atol=1e-8 '
           'все 46080 бинарных R/B решений D1 совпали точно.','',
           '[Независимый D2 audit](group-runtime-v1/d2/runtime-audit.json) подтвердил R/B, '
           'все 184320 causal temporal candidates, сегментацию, duration и IF support. '
           'Все 829440 локальных B1 score совпали с прежним экспортом, 14341 positives.','',
           '## R/B/Y и зависимость','',
           '| R | B | Group ticks | Доля всех известных |','|---|---|---:|---:|',
           f"| positive | positive | {r['joint']} | {r['joint']/r['known']:.6%} |",
           f"| positive | negative | {r['r_only']} | {r['r_only']/r['known']:.6%} |",
           f"| negative | positive | {r['b_only']} | {r['b_only']/r['known']:.6%} |",
           f"| negative | negative | {r['neither']} | {r['neither']/r['known']:.6%} |",'',
           f"R positives: {r['joint']+r['r_only']}; B positives: {r['joint']+r['b_only']}. "
           f"Jaccard={r['jaccard']:.6f}, phi={r['phi']:.6f}; "
           f"P(B+|R+)={r['p_b_given_r']:.6f}, P(R+|B+)={r['p_r_given_b']:.6f}. "
           'Методы связаны, но не тождественны: особенно велик B-only набор. '
           'Для a02 phi=0.710639; единая pooled статистика скрывает неоднородность групп. '
           'Это описательные числа зависимых временных рядов, не независимые Bernoulli '
           'испытания и не оценки fault FPR. Вероятности ошибок не перемножаются.','',
           '**Y unknown во всех 46080 group ticks**: `approved_sensor_bounds=[]`. '
           'Это отсутствие применимого аппаратного заключения, не отрицательный Y. '
           'Полное голосование с доступным Y на реальных данных не оценивается; '
           'код device→host→group проверяется искусственными тестовыми bounds. '
           '300 W GPU и 2200 W PSU не использованы как аварийные пороги.','',
           '| Группа | R+ | B+ | R&B | R-only | B-only | Phi | R+ с zero-MAD в паре | Events δ0 |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for group,c in counts.items():
        d=analysis['by_group'][group];ne=sum(e['group']==group and e['delta_seconds']==0 for e in events)
        lines.append(f"| {group} | {c['r_positive']} | {c['b_positive']} | {d['joint']} | {d['r_only']} | {d['b_only']} | {d['phi']:.6f} | {c['r_positive_zero_mad_pair']} | {ne} |")
    lines+=['','## Время и предварительные события','',
            'Все события имеют `mode=preliminary`, `criteria_incomplete=true`, '
            '`hardware_confirmation=insufficient_criteria`. Raw R/Y/B, temporal occurrence, '
            'общее vote2 и preliminary intersection разделены. Причинный TTL использует '
            'только предыдущие/текущий ticks. Unknown R/B или gap прерывает событие; '
            'известный отрицательный tick закрывает на текущем времени с сохранением '
            'предыдущего last_positive. Нет gap merging и повторов ID на длинном событии.','',
            '| δ, s | Candidate ticks | Events | Сумма group duration, s | Max duration, s | IF supported / none | Zero-MAD pair events | Max pair delay, s | Jaccard temporal |','|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for delta,d in analysis['by_delta'].items():
        lines.append(f"| {delta} | {d['candidate_ticks']} | {d['events']} | {d['duration_seconds']} | {d['maximum_duration_seconds']} | {d['if_supported_events']} / {d['no_if_support_events']} | {d['zero_mad_pair_events']} | {d['maximum_confirmation_delay_seconds']} | {d['dependency']['jaccard']:.6f} |")
    lines+=['','Duration суммируется по группам и включает последнюю 10 s ячейку; '
            'это не wall-clock длительность одного кластерного инцидента. TTL увеличивает '
            'занятость и может соединять близкие срабатывания; число событий не обязано '
            'монотонно расти. Основной вариант остаётся δ=0; лучший δ не выбирался. '
            'Полная таблица: [events.csv](group-runtime-v1/d2/events.csv), '
            '[events.json](group-runtime-v1/d2/events.json).','',
            '![Сравнение временных допусков](group-runtime-v1/d2/figures/delta-sensitivity.png)','',
            '## Zero-MAD: существенное ограничение интерпретации','',
            f"В {analysis['zero_mad_pair_r_ticks']} из 899 R-positive ticks "
            f"({analysis['zero_mad_pair_r_ticks']/899:.2%}) определяющая пара содержит zero-MAD канал. "
            'При δ=0 это 42 из 285 событий. Хосты не исключались, floor не изменялся.','',
            '| Хост | R+ above Q99 | В определяющей паре | Амплитуда min/max, °C | Min / median abs amplitude в паре, °C | Max abs(z) |','|---|---:|---:|---:|---:|---:|']
    for host,z in analysis['zero_mad'].items():
        lines.append(f"| {host} | {z['r_positive_above_threshold_ticks']} | {z['defining_pair_ticks']} | {z['amplitude_C_min']:.6f} / {z['amplitude_C_max']:.6f} | {z['defining_pair_amplitude_abs_C_min']:.6f} / {z['defining_pair_amplitude_abs_C_median']:.6f} | {z['abs_z_max']:.3f} |")
    lines+=['','Для a02: 187 из 199 R-positive ticks включают zero-MAD в определяющую '
            'пару. Порог R=65.762598 соответствует всего 0.00657626 °C для канала с '
            'scale=1e-4 °C. Минимальная наблюдаемая амплитуда в такой паре около '
            '0.016667 °C уже даёт |z|≈166.7. Поэтому большие score здесь нельзя '
            'интерпретировать как физически сильный/опасный перегрев. Изменения '
            'температуры реальны в данных, но их статистический масштаб определяется '
            'численным floor; без модели sensor noise/дискретности это потенциальный '
            'блокер физической интерпретации a02. Остальные группы не сводятся к этому '
            'случаю: a09/a11 имеют более крупные отклонения, прочие группы не содержат '
            'известных zero-MAD каналов в определяющих парах. Это не доказывает их аппаратную природу.','',
            'Воспроизводимые значения: [zero-mad-evidence.csv](group-runtime-v1/d2/zero-mad-evidence.csv), '
            '[zero-mad-series.csv](group-runtime-v1/d2/zero-mad-series.csv).','',
            'Количество δ0 событий по zero-MAD хостам: a02n09 — 11, a02n10 — 12, '
            'a09n05 — 16, a11n12 — 14; события могут включать несколько таких хостов, '
            'эти числа не складываются. Полный δ grid: '
            '[context-analysis.json](group-runtime-v1/d2/context-analysis.json).','',
            '![Все четыре zero-MAD канала](group-runtime-v1/d2/figures/zero-mad-channels.png)','',
            '## Детерминированный пример и физические величины','',
            f"Самое длинное δ=0 событие: **{selected['group']}**, "
            f"{selected['detected_event_time']} — {selected['last_positive_time']}, "
            f"закрыто {selected['closed_event_time']}; duration={selected['duration_grid_seconds']} s. "
            f"Хосты-свидетели: {', '.join(selected['witness_hosts'])}; IF support "
            f"{selected['if_supported_ticks']}/{selected['positive_ticks']} ticks; "
            f"zero-MAD pair {selected['zero_mad_pair_ticks']}/{selected['positive_ticks']}. "
            'Выбран автоматическим правилом longest, затем group/time; здесь наиболее '
            'длительный пример как раз демонстрирует ограничение, а не сильнейшее '
            'доказательство аппаратной неисправности. На графике мощности и температуры '
            'даны в исходных физических единицах после явно указанной групповой агрегации.','',
            '![Физические каналы, R/B, Y, события и IF/E](group-runtime-v1/d2/figures/event-example.png)','',
            '## IF и межгрупповое сравнение','',
            'S=a/n использует только доступные локальные решения. На реальном D2 все '
            '18 узлов доступны; 274 δ0 события имеют хотя бы один IF-positive tick, '
            '11 событий не имеют такой поддержки. IF не является gate. Индивидуальные '
            'score/threshold/hostname сохранены для всех 829440 состояний в raw NDJSON; '
            'компактный [r-evidence.ndjson](group-runtime-v1/d2/r-evidence.ndjson) публикует '
            'все 899 R-positive строки с физическими свидетелями и локальными IF решениями.','',
            'E=S−S_outside вычислен с весами числа доступных хостов и исключением '
            'текущей группы; сохранён outside universe. Для 4/8/16 групп outside различен. '
            'E не фильтрует событие. Нулевой/отрицательный E не исключает общего изменения режима.','']
    lines += [f"При δ0 union R-witness hosts на событие: {context['witness_count_delta0']['min']}–{context['witness_count_delta0']['max']}. "
              f"Из 682 candidate ticks E>0 в {context['spatial_delta0']['positive_E_candidate_ticks']}, "
              f"E≤0 в {context['spatial_delta0']['nonpositive_E_candidate_ticks']}. "
              'Контекст каждого события: [event-context.csv](group-runtime-v1/d2/event-context.csv); '
              'непрерывные интервалы совпадения с IF: [if-overlap-intervals.csv](group-runtime-v1/d2/if-overlap-intervals.csv).','']
    hist=analysis['by_delta']['0']['simultaneous_groups_histogram']
    lines += [f"При δ0: {hist[1]} timestamps с ровно одной активной группой, "
              f"{sum(hist[2:16])} с 2–15 группами, {hist[16]} с 16 группами; "
              f"{hist[0]} без кандидатов. Это описывает охват. Синхронность не "
              'доказывает общий PDU/охлаждение/инцидент; возможны общие изменения нагрузки.','',
              '![Все группы, IF и неизвестный Y](group-runtime-v1/d2/figures/cluster-activity.png)','',
              '![Распределение R/B и событий](group-runtime-v1/d2/figures/group-distribution.png)','',
              '## Производительность','',
              f"Среда: {performance['platform']}, {performance['processor']}, Go 1.27.2, "
              'amd64, GOMAXPROCS=16. Последовательные отдельные процессы; 3 повтора '
              'на размер, warm OS cache после первого full run, cache eviction не выполнялся. '
              'Reader читает общий Parquet всех 16 групп даже для меньшего scoring universe.','',
              '| Groups | Process wall median [min,max], s | Analysis median, s | Host states/s median | Peak WS [min,max], MiB | Sampled heap max, MiB |','|---:|---:|---:|---:|---:|---:|']
    for n in [4,8,16]:
        a=[x for x in performance['rows'] if x['groups']==n];walls=[x['wall_seconds'] for x in a];mem=[x['peak_working_set_bytes']/2**20 for x in a]
        lines.append(f"| {n} | {statistics.median(walls):.4f} [{min(walls):.4f},{max(walls):.4f}] | {statistics.median(x['analysis_seconds'] for x in a):.4f} | {statistics.median(x['host_states_per_second'] for x in a):.1f} | {min(mem):.2f}–{max(mem):.2f} | {max(x['sampled_peak_heap_bytes'] for x in a)/2**20:.2f} |")
    lines+=['',f"Отдельный **полный materialized 16-group run**: process wall {full['wall_seconds']:.4f} s, "
            f"analysis {full['analysis_seconds']:.4f} s, peak Windows working set {full['peak_working_set_bytes']/2**20:.2f} MiB, "
            f"sampled heap {full['sampled_peak_heap_bytes']/2**20:.2f} MiB. "
            'Peak working set — process-lifetime показатель Windows, не sampled heap и не '
            'обещание linux RSS. Heap считывается каждые 30 ticks и может пропускать пики. '
            'Полный wall включает загрузку/валидацию/SHA и финальную запись; native analysis '
            'не включает подготовку моделей. JSON/reader/outside overhead входит в общий '
            'analysis, но не в отдельные kernel timers.','',
            '| Стадия полного run | Seconds |','|---|---:|']
    for key,value in full['timing'].items():lines.append(f'| {key} | {value:.6f} |')
    lines+=['','Полные повторы, команды, binary SHA и модели: '
            '[performance.json](group-runtime-v1/performance.json), '
            '[performance-full.json](group-runtime-v1/performance-full.json). '
            'Профили общих групп не переобучались. Улучшение throughput при большем '
            'universe частично связано с фиксированным I/O; это не доказательство '
            'линейного масштабирования и не задержка будущей Kafka-системы.','',
            '## Сложность и воспроизводимость','',
            'H=18G, K=5, d=10, F=число IF trees, L=depth. Inference: '
            'O(T·H·F·L + T·H·K + T·G·d² + T·G²) — последняя часть есть в текущем '
            'прямом outside comparison. Temporal четыре δ — постоянный множитель, '
            'память самой temporal части O(G) с тремя latest-positive/unknown состояниями и bounded summaries; '
            'сырые свидетельства пишутся потоково. Event witness union ограничен 18 хостами. '
            'Полная Go inference память дополнительно содержит group profiles O(H·K+G·d²), '
            'существующий лес O(F·sample_size), decoder и audit maps O(T+H) в переиспользованном '
            'Source.Scan; поэтому весь runner не объявляется O(1) по длительности окна. '
            'Fit хранит O(T1·H·K + T1·G·d), точные medians/quantiles требуют сортировки '
            'O((H·K+G·d)·T1 log T1), covariance O(T1·G·d²), SVD O(G·d³), '
            'текущая прямая reconstruction diagnostic O(G·d⁴). '
            'Python визуализация дополнительно хранит T×G массивы и не является памятью Go inference.','',
            'Запуск и форматы: [group-detection-runtime.md](group-detection-runtime.md). '
            'Источники графиков: [timeline.csv](group-runtime-v1/d2/timeline.csv), '
            '[temporal.csv](group-runtime-v1/d2/temporal.csv), events/zero-MAD CSV/JSON. '
            'Каждый график сохранён в PNG и SVG. Полные большие raw/temporal NDJSON '
            'остаются в новом `results/group-runtime-d2-v1`, воспроизводятся CLI и '
            'не добавлены в Git из-за размера. Все 899 R-positive evidence опубликованы.','',
            '## Приёмка и ограничения','',
            'Выполнены Go test/build/vet, Python regressions, D1 parity, независимый D2 '
            'math/temporal/B1 audit и protected SHA audit. Точные результаты финальной '
            'проверки сохранены в [validation.json](group-runtime-v1/validation.json). '
            'Аппаратные fault Precision/Recall/F1 не вычисляются: независимой разметки '
            'нет. D1 — один автокоррелированный 8h фрагмент; D2 исследовательский, '
            'а не независимая итоговая проверка. Число событий — не число отказов. '
            'См. [limitations](group-detection-limitations.md).','',
            'Фактические роли: Orchestrator GPT-6.1 Sol / High; Implementer GPT-6 Luna / '
            'Medium (Y/temporal, исправлено главным при приёмке); Test Writer GPT-6 Luna / '
            'Low (контрактные тесты, дополнены главным). Все model/effort — configured '
            'по проектным TOML, runtime metadata не подтверждены. Других агентов не было.','']
    with args.output.open('x',encoding='utf-8',newline='\n') as f:f.write('\n'.join(lines))


if __name__=='__main__':main()
