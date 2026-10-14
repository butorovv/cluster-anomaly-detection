"""Deterministic tables from stage I outputs; scientific interpretation is explicit."""
import argparse
import json
import hashlib
from pathlib import Path
import numpy as np

DOCS=Path('docs/research-4.3')


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |',
                      *['| '+' | '.join(str(v) for v in row)+' |' for row in rows]])+'\n'


def pct(a,b):return f'{100*a/b:.2f}%' if b else '—'
def fmt(x):return f'{x:.6g}' if x is not None else '—'
def interval(x):return '['+', '.join(f'{100*v:.2f}' for v in x)+']' if x is not None else '—'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=Path('results/research43-v4'))
    args=p.parse_args()
    summary=json.loads((args.output/'summary.json').read_text());base=summary['baseline']
    audit=json.loads((args.output/'audit.json').read_text());rows=json.loads((args.output/'events.json').read_text())
    all_=summary['aggregates']['all'];n=summary['events']
    baseline=['# Этап 0: baseline и воспроизводимость\n',
        'Дата 14.10.2026. Baseline **совпадает** с ТЗ. Новый полный Go-export A0/Mahalanobis D2 '
        'побайтно совпал с экспортом №4.1. B1/B2 и seed43/44 проверены повторной арифметикой '
        'неизменных экспортов и независимым прямым обходом сохранённых деревьев. '
        '**Повторное обучение всех шести лесов в этой работе не выполнялось.**\n',
        '## Git и последовательность включения\n',
        table(['Ветка после успешного fetch','SHA','Состояние'],[
            ['main','1dfb7c1f8b011b64a8fdebe4de4cdaafc3438940','база обоих исследований'],
            ['research/d2-anomaly-diagnostics','79a144125ba5a05d21a999516e210ba6e604e6e2','2 собственных коммита; не в main/4.2'],
            ['research/context-aware-isolation','98aab5865a9ee8d0d59c8fe51954047abab32ef8','3 собственных коммита; не в main'],
            ['research/power-asymmetry-4-3','база 98aab586…','текущие этапы 0/I']]),
        'Рекомендация: отдельно согласовать включение №4.1, затем перенести/проверить №4.2 '
        'на обновлённой базе, затем №4.3. Ветки 4.1/4.2 — соседние, merge-base равен main. '
        'Merge/cherry-pick не выполнялись. №4.3 создан от №4.2. Минимальная зависимость 4.1 '
        'закреплена четырьмя побайтными исходниками в tools/research43/vendor/research41; '
        'это явная зависимость, без объединения историй и без переноса старых отчётов.\n',
        '## Протокол и сохранность\n',
        'D1: 18.01.2022 [00:00,08:00); D2: [08:00,16:00), assumed UTC. '
        'В каждом 288×2880=829440 состояний, полный F18. Последняя отметка D2 '
        f"{summary['latest_timestamp']}. D3 не участвует в обучении, scoring, статистике или калибровке. "
        'Hash полного Parquet проверяет сохранность байтов. timezone_verified=false; '
        'геометрия групп hostname не равнозначна доказанному графу инфраструктуры.\n',
        'Версии: statistical-v1, isolation-forest-v1, physical-v1, isolation-calibration-v1; '
        'лес 100 деревьев, ψ=256, depth=8, seed42 (дополнительно 43/44). '
        'Q99 — наблюдение с индексом ceil(.99n), строгий знак >, без интерполяции.\n',
        table(['Метод','D2 сигналов','4 a02','Совпадений с переходами','Доля событий'],[
            [name,r['signals'],pct(r['four_signals'],r['signals']),r['physical_coincidences'],pct(r['physical_coincidences'],n)]
            for name,r in base['counts'].items()]),
        f"Mahalanobis D²>{77.70489690680702}: {base['mahalanobis_signals']} состояний. "
        'IF/Mahalanobis: TP_ref=2607, FP_ref=10240, FN_ref=7273, TN_ref=809320. '
        'F1_ref=0.2294187530250363 — согласование критериев, не точность отказов.\n',
        table(['Метод','Внутригрупповые пары','Среднее 1999 разбиений','Отношение','Точное ожидаемое отношение'],[
            [r['method'],int(r['actual']),fmt(r['control_mean']),fmt(r['effect_ratio']),fmt(r['exact_ratio'])] for r in base['topology']]),
        'Сохранённые перестановки seed4202 заново арифметически оценены; новые разбиения '
        'не генерировались. Прежние 1999 временных сдвигов seed42 дают Holm64 p=.032 '
        'для pair-bins a12–a16. Это проверка воспроизводимости прежнего контроля.\n',
        '## SHA-256 входов и производных артефактов\n',
        table(['Вход','SHA-256'],[[k,v] for k,v in base['input_sha256'].items()]),
        '## Независимая численная проверка\n',
        table(['Проверка','Наблюдаемый результат'],[
            ['Direct tree oracle',f"6 лесов × 2 окна × 1024 состояний; max error={max(base['score_max_errors'].values()):.3g}"],
            ['Mahalanobis прямое матричное вычисление',f"max error={base['mahalanobis_max_error']:.3g}"],
            ['Host medians независимой сортировкой',fmt(base['median_max_error'])],
            ['Квантили независимой сортировкой','полное совпадение'],
            ['Новый Go-export D2',str(audit['full_fresh_go_D2_replay_equal'])],
            ['Новый states.bin SHA-256',audit['fresh_go_binary_sha256']],
            ['Исходные hashes до/после','совпадают']]),
        'Схема №4.1 хранит availability=1 как boolean; №4.2 хранит F18 bitmask=262143. '
        'Проверен одинаковый смысл доступности. Timestamp, host, F18, A0 score и D² '
        'совпадают по всем строкам. Первоначальная проверка ошибочно сравнила эти '
        'разные представления как одинаковые поля и остановилась; проверка исправлена, '
        'научные параметры не изменялись, старые результаты не перезаписаны.\n',
        '## Проверки и восстановление\n',
        '[Команды и tracked зависимость](../../tools/research43/README.md). '
        '[План 0–VI и блокеры](STAGE-PLAN.md). Итоговые checks перечислены в CHECKS.md. '
        'Baseline сохранён отдельно: '+str(args.output/'baseline.json')+'.\n']
    (DOCS/'00-baseline-and-reproducibility.md').write_text('\n'.join(baseline),encoding='utf-8')
    content=['# Этап I: асимметрия мощности и временной оценки\n',
        '**Асимметрия подтверждена на реальных D2 событиях, но не свидетельствует сама по себе '
        'о программной ошибке IF.** При снижении мощности новые состояния чаще получают высокий '
        'контекстный score; повышение, особенно PSU, часто возвращает узел из уже отмеченного '
        'малого уровня мощности. IF оценивает редкость состояния, а не знак изменения мощности. '
        'Увеличивать долю обнаруженных повышений без определения исследуемого состояния нельзя.\n',
        'Дата 14.10.2026. [Зафиксированный до расчёта протокол](01-analysis-protocol.md); '
        f"SHA-256 {summary['protocol_sha256']}. D1/D2 и hashes: [этап 0](00-baseline-and-reproducibility.md). "
        'D2 исследовательский; независимая итоговая валидация отсутствует.\n',
        '## Отбор и состояние до/после\n',
        '6978 прежних событий №4.2, без изменения критериев. t — представитель с максимальным '
        'нормированным 60-секундным приращением в объединённом событии. Его направление задаёт '
        'доминирующая подсистема: увеличение одной мощности не означает рост всех 18 координат. '
        f"{all_['mixed_directions']} событий содержат одновременно сильные приращения разных знаков; "
        f"{all_['overlapping']} событий имеют пересекающиеся исходные окна другого события того же хоста. "
        'Это число событий, не независимых отказов.\n',
        'Pre — покоординатная медиана [-120,-60] с; post — медиана [0,+30] с. '
        'Температуры CPU/GPU средние по 2/6 компонентам. Температура PSU в F18 отсутствует. '
        'Агрегированный median F18 не обязан совпадать с одной реальной строкой: расстояние '
        'до D1 ниже является описанием агрегата, а не доказательством существования такого режима.\n',
        table(['Категория','N','pre/post P доминирующей, W (median)','pre/post A0 (median)','pre/post B2 (median)',
               'post D1-host percentile A0/B2 (median)','pre/post nearest D1'],[
            [cat,v['n'],f"{fmt(v['distributions']['power_before_'+cat.split()[0]]['q50'])}/{fmt(v['distributions']['power_after_'+cat.split()[0]]['q50'])}",
             f"{fmt(v['distributions']['a0_before']['q50'])}/{fmt(v['distributions']['a0_after']['q50'])}",
             f"{fmt(v['distributions']['b2_before']['q50'])}/{fmt(v['distributions']['b2_after']['q50'])}",
             f"{fmt(v['distributions']['a0_host_D1_percentile_after']['q50'])}/{fmt(v['distributions']['b2_host_D1_percentile_after']['q50'])}",
             f"{fmt(v['distributions']['nearest_D1_before']['q50'])}/{fmt(v['distributions']['nearest_D1_after']['q50'])}"]
            for cat,v in summary['aggregates'].items() if cat!='all']),
        'Nearest D1 — Euclidean расстояние в прежних глобальных F18 scale до каждой шестой '
        'D1 строки своего хоста (480 состояний). Не оценка плотности; редкие обучающие состояния '
        'могут быть пропущены подвыборкой. ECDF score также не доказывает многомерное совпадение. '
        'Полные распределения и квантили всех координат: [приложение](01-distributions.md).\n',
        '![ECDF изменений score](figures/score-change-ecdf.png)\n',
        '![Представленность относительно D1](figures/d1-representation.png)\n',
        '## Что старая метрика называла обнаружением\n',
        'Any — любой положительный сигнал в указанном закрытом окне. New — false→true после t '
        'при отсутствии сигналов последние 60 с до t. Это более строгое определение нового '
        'сигнала, а не доказанный аппаратный детектор. Существовавший ранее сигнал может быть '
        'содержательным состоянием; его нельзя автоматически отнести к новому переходу.\n',
        table(['Категория','Метод','Any [-30,+180]','Any [0,+120]','New [0,+120]','pre120','active t−10','post-onset [0,+120]'],[
            [cat,name,pct(v['methods'][name]['windows']['historical']['any'],v['n']),
             pct(v['methods'][name]['windows']['120s']['any'],v['n']),pct(v['methods'][name]['windows']['120s']['fresh_onset'],v['n']),
             pct(v['methods'][name]['windows']['120s']['pre120'],v['n']),pct(v['methods'][name]['windows']['120s']['active_before'],v['n']),
             pct(v['methods'][name]['windows']['120s']['post_onset'],v['n'])]
            for cat,v in summary['aggregates'].items() for name in ['B1','B2']]),
        'Расширение времени и старые сигналы совместно завышали впечатление чувствительности: '
        f"B1 {pct(2352,n)} any historical → {pct(all_['methods']['B1']['windows']['120s']['fresh_onset'],n)} new120; "
        f"B2 {pct(2625,n)} → {pct(all_['methods']['B2']['windows']['120s']['fresh_onset'],n)}. "
        'Эта разница включает и сокращение окна до 120 с; отдельное сравнение при одинаковом '
        'окне [-30,+180] доступно в таблицах ниже. Асимметрия сохраняется в коротких окнах.\n',
        '![Чувствительность временных окон](figures/window-sensitivity.png)\n',
        table(['Категория','Метод','Any30/60/120/old, %','New30/60/120/180, %','pre-only old','Latency new/post median/q95, s'],[
            [cat,name,' / '.join(pct(v['methods'][name]['windows'][w]['any'],v['n']) for w in ['30s','60s','120s','historical']),
             ' / '.join(pct(v['methods'][name]['windows'][w]['fresh_onset'],v['n']) for w in ['30s','60s','120s','historical']),
             v['methods'][name]['windows']['historical']['pre_only'],
             '/'.join(fmt(v['methods'][name]['windows']['120s']['latency'].get(q)) for q in ['q50','q95'])]
            for cat,v in summary['aggregates'].items() for name in ['A0 historical','A0 D1-Q99','B1','B2','Power increment']]),
        'Latency и duration таблиц относятся ко всем новым post-onsets, включая случаи '
        'сигналов ранее в pre60; для строго fresh события доступны индивидуальные записи. '
        'Нельзя воспринимать latency относительно представителя t как задержку от начала '
        'всего перехода. Продолжительность run включает выход за окно оценки; right censor '
        'в конце D2 отмечен. Физическая длительность определяется по возврату через midpoint.\n',
        table(['Категория','Физический режим duration median/q95, s','undefined/censored','B1 onset duration median/q95','B2 onset duration median/q95'],[
            [cat,'/'.join(fmt(v['regime']['duration'].get(q)) for q in ['q50','q95']),f"{v['regime']['undefined']}/{v['regime']['censored']}",
             '/'.join(fmt(v['methods']['B1']['windows']['120s']['onset_duration'].get(q)) for q in ['q50','q95']),
             '/'.join(fmt(v['methods']['B2']['windows']['120s']['onset_duration'].get(q)) for q in ['q50','q95'])]
            for cat,v in summary['aggregates'].items() if cat!='all']),
        '## Сопоставимые реальные контроли\n',
        f"Подобрано {summary['matched']}/{n} ({pct(summary['matched'],n)}) пар; {n-summary['matched']} unmatched. "
        'Тот же host/час, тот же D1-дециль предыдущей мощности, полная доступность; '
        'в [-120,+180] нет coverage сильного перехода. IF score при отборе не использован. '
        'Контроли не размечены как исправные. Повторные центры запрещены, окна могут '
        'пересекаться. Bootstrap целых host, часов и получасов сохраняет совместные пары.\n',
        table(['Категория','Пар','Метод','Event/control new120, %','Δ, п.п.','CI host, п.п.','CI hour, п.п.','CI halfhour, п.п.'],[
            [cat,v['matched'],name,pct(r['event_fresh'],v['matched'])+'/'+pct(r['control_fresh'],v['matched']),
             fmt(100*r['host_ci']['difference']) if r['host_ci']['difference'] is not None else '—',
             interval(r['host_ci']['interval95']),interval(r['hour_ci']['interval95']),interval(r['halfhour_ci']['interval95'])]
            for cat,v in summary['aggregates'].items() for name in ['A0 historical','A0 D1-Q99','B1','B2','Power increment']
            for r in [v['methods'][name]['windows']['120s']['paired']]]),
        'Для GPU rise у B1 интервалы по времени включают ноль; для CPU rise у B2 — также. '
        'Для PSU rise новые сигналы отсутствуют, тогда как в реальных контролях возникают. '
        'Эти наблюдения согласуются с возвращением в обычный режим, а не с недостаточным '
        'временным окном. Нельзя объявить причинность или точность по такой выборке.\n',
        'Bootstrap: PCG64 seed4301, 1999 повторов. Всего 8 общих часовых блоков; CI '
        'описательные, не одновременные по всем категориям, без окончательных p-values. '
        'Отдельный host-bootstrap не учитывает общие временные шоки, time-bootstrap не '
        'решает полностью зависимость одних host между блоками. Приведены оба и sensitivity '
        '30 мин; полноценное многомерное/многоуровневое подтверждение требует новых дней.\n',
        'Проверка граничных контролей выявила, что coverage прежних событий не включает '
        'сырые сильные приращения, чьи представители исключены краями D2. Исправлено '
        'объединением coverage с сырыми D1-калиброванными превышениями, в том числе '
        'первым 60-секундным lookback из D1. Это исправление условия контроля, '
        'без изменения порогов, событий и new-onset. Окончательные результаты — '
        'research43-v4; прежние v2/v3 сохранены отдельно как промежуточные.\n',
        'Дополнительные ограничения: пары по мощности могут иметь большой разрыв внутри '
        'широкого дециля; различается доля исходных pre-сигналов, поэтому вероятность fresh '
        'зависит от возможности начать новый run. Контрольный результат относится ко всем '
        'парам, а не к одинаковому risk set нормального оборудования.\n',
        table(['Качество сопоставления |Δpre P|, W','n','q50','q95','max'],[
            ['Все matched',*[fmt(v) for v in [len([r for r in rows if r['control_t'] is not None]),
             float(np.median([r['control_power_mismatch'] for r in rows if r['control_t'] is not None])),
             float(np.quantile([r['control_power_mismatch'] for r in rows if r['control_t'] is not None],.95)),audit['max_power_mismatch_W']]]]]),
        '## Простой физический baseline и информация IF\n',
        'Power increment: любое |Δ60 P_j|>D1 Q99.5_j; пороги GPU/CPU/PSU '
        +'/'.join(fmt(v) for v in base['physical_thresholds']['power'])+' W. '
        'Any-signal отмечает все 6978 событий **по конструкции их отбора**. Это не 100% '
        'чувствительность к отказам. Контроли специально исключают сильные переходы, '
        'поэтому нулевая частота физического baseline в них также задана отбором.\n',
        'Для определения именно этих крупных приращений необходимость IF не доказана: '
        'простого порога достаточно. IF добавляет оценку редкости получившегося состояния '
        'в F18, сохранение абсолютных экстремумов и устойчивых режимов; это другие свойства, '
        'а не подтверждённое преимущество в обнаружении отказов. B1/B2 дают ненулевые '
        'сигналы и в окнах без сильных переходов.\n',
        table(['Категория','A0 без crossing, но Δscore','B1 без crossing, но Δscore','B2 без crossing, но Δscore'],[
            [cat,*[v['methods'][name]['continuous_without_crossing'] for name in ['A0 D1-Q99','B1','B2']]]
            for cat,v in summary['aggregates'].items()]),
        'Ненулевой Δscore не имеет независимого порога значимости: эта таблица показывает '
        'информацию, которую бинаризация скрывает, а не новые успешные detections.\n',
        '## Диагностическое дополнение: непосредственная пара t−60/t\n',
        'После основного расчёта добавлен описательный разбор непосредственно тех двух '
        'реальных строк, по которым выделялось Δ60. Первоначальный протокол, события, '
        'пороги, контроли и primary метрики не изменены. Это дополнение после просмотра '
        'результатов, а не заранее зарегистрированная отдельная гипотеза.\n',
        table(['Категория','P(t−60)/P(t), W median','B2(t−60)/B2(t) median','t−start median/q95, s',
               'Оба знака доминирующей подсистемы внутри merged event'],[
            [cat,'/'.join(fmt(v['distributions'][f'{key}_{cat.split()[0]}']['q50']) for key in ['power_at_t_minus60','power_at_t']),
             '/'.join(fmt(v['distributions'][key]['q50']) for key in ['b2_at_t_minus60','b2_at_t']),
             '/'.join(fmt(v['distributions']['representative_delay_seconds'][q]) for q in ['q50','q95']),
             f"{v['both_directions_in_merged_component']}/{v['n']}"]
            for cat,v in summary['aggregates'].items() if cat!='all']),
        'Эти непосредственные состояния нельзя заменять медианами длинного окна: '
        'median сглаживает короткое падение/возврат. Физическая midpoint-duration '
        'имеет median 20 с для GPU/CPU и PSU drop, а B2 onset-run обычно 10 с. '
        'Часть post medians вообще не меняется в направлении выбранного Δ60: '
        'duration тогда undefined. Поэтому утверждение о длительном новом режиме '
        'для всех 6978 событий отвергнуто. Частые pre-сигналы у rise могут относиться '
        'к краткому минимуму мощности перед возвратом; job completion без журналов '
        'остаётся недоказанным объяснением. Отбор максимума в длинном merged событии '
        'также влияет на направление и измеренную задержку.\n',
        '## Причины: подтверждённые связи и оставшиеся гипотезы\n',
        '1. Подтверждено: после drop B2 score и относительная D1 редкость значительно выше, '
        'после rise PSU/GPU они ниже или близки к исходному уровню. Выбор состояния до/после '
        'и его представленность на D1 объясняют направление статистической реакции.\n'
        '2. Подтверждено: rise часто следует за pre-сигналом; широкий any-window '
        'смешивал прежнюю нетипичность с новым сигналом. Сокращение окна и new-onset '
        'не устраняют асимметрию.\n'
        '3. Подтверждено: B1 и B2 оба асимметричны, хотя B2 имеет единый порог. '
        'Следовательно индивидуальные theta_h не являются достаточным объяснением '
        'эффекта. Они меняют абсолютные частоты и категории, см. margins приложения.\n'
        '4. Следует из реализованной модели: IF работает с одним состоянием, не содержит '
        'знака/лага мощности как отдельного признака. Его высокий score — короткий путь '
        'изоляции в обученной системе координат, а не индикатор любого физического скачка.\n'
        '5. Не установлено: что drop — завершение задания, что rise — исправление '
        'оборудования, что общая асимметрия — самостоятельное свойство IF на любой '
        'популяции. Нужны job logs, независимая временная зона, этап III и другие дни.\n',
        '## Хосты, группы и реальные примеры\n',
        table(['Категория','Метод','Max group support в [0,+120], q50/q95/max'],[
            [cat,name,'/'.join(fmt(v['methods'][name]['max_group_fraction'].get(q)) for q in ['q50','q95','max'])]
            for cat,v in summary['aggregates'].items() if cat!='all' for name in ['B1','B2']]),
        '[Все 288 хостов и 16 групп, drop/rise](01-host-group-breakdown.md). '
        'Разбиение подтверждает неоднородность, но не причинную инфраструктурную локализацию. '
        'Групповой критерий этапа IV пока не создан. Примеры выбраны фиксированным правилом '
        '(max amplitude, первое несогласие B1/B2, первый пропуск), без ручной оптимизации.\n',
        table(['Категория','Host/UTC assumed','Δ60 GPU/CPU/PSU, W','Any120 B1/B2','New120 B1/B2','График'],[
            [ex['category'],r['host']+'/'+r['timestamp'],'/'.join(fmt(v) for v in r['delta60']),
             '/'.join(str(int(r['methods'][m]['windows']['120s']['any'])) for m in ['B1','B2']),
             '/'.join(str(int(r['methods'][m]['windows']['120s']['fresh_onset'])) for m in ['B1','B2']),
             f"[event-{r['index']}](figures/event-{r['index']}.png)"]
            for ex in summary['examples'] for r in [rows[ex['index']]]]),
        '## Решение контрольной точки №1\n',
        'Есть основания разделить абсолютную и индивидуальную контекстную оценки и '
        'проверить отдельное временное изменение, если задача требует отмечать оба направления. '
        'Нет оснований менять F18 или основной IF ради более высокой доли совпадений '
        'с заранее выделенными скачками. B1/B2 победителем не назначены; преимуществ '
        'сложного IF для самого обнаружения крупных приращений не доказано.\n',
        '[Протокол H1/H2 и условной H3](02-hypotheses-protocol.md) представлен для '
        'согласования. Реализация новых кандидатов остановлена согласно ТЗ §12/§15.\n',
        '## Проверки и ограничения воспроизводимости\n',
        f"Audit: {audit['independent_temporal_checks']} независимых проверок закрытых окон, "
        f"{audit['unique_matched_controls']} уникальных контролей, host/hour/decile/coverage совпадают. "
        'Исходные SHA до/после совпадают; D3 не scoring. Проверки кода — CHECKS.md. '
        f"Полный расчёт занял {summary['elapsed_seconds']:.2f} с в данной среде; это один запуск, "
        'не результат масштабируемости VI. Версии: '+', '.join(f'{k} {v}' for k,v in summary['versions'].items())+'.\n',
        'Подробные JSON в ignored '+str(args.output)+' восстанавливаются tracked кодом. '
        'Сохранённые физические события не являются независимой истинной разметкой.\n']
    (DOCS/'01-power-asymmetry.md').write_text('\n'.join(content),encoding='utf-8')
    distributions=['# Распределения этапа I\n','Все единицы как в именах: power W, temperature °C, score безразмерный. '
                   'relative_delta безразмерный; D1 percentile от 0 до 1. Квантили inverted_cdf. '
                   'Время: s. Полный event JSON также содержит все 18 z координат.\n']
    for category,v in summary['aggregates'].items():
        distributions.extend([f'## {category}\n',table(['Показатель','n','mean','min','q01','q25','q50','q75','q95','q99','max'],[
            [name,*[fmt(d.get(k)) for k in ['n','mean','min','q01','q25','q50','q75','q95','q99','max']]]
            for name,d in v['distributions'].items()])])
    (DOCS/'01-distributions.md').write_text('\n'.join(distributions),encoding='utf-8')
    breakdown=['# Разбивка по хостам и группам\n','New = fresh onset [0,+120] при pre60 без сигналов. '
               'Группы имеют 18 хостов; не являются доказанными физическими доменами отказов.\n']
    for key in ['groups','hosts']:
        breakdown.extend([f'## {key}\n',table(['ID','Событий','Matched','B1 drop new/N','B1 rise new/N','B2 drop new/N','B2 rise new/N'],[
            [r['label'],r['events'],r['matched'],*[f"{r[k]['new']}/{r[k]['n']}" for k in ['B1_drop','B1_rise','B2_drop','B2_rise']]]
            for r in summary[key]])])
    (DOCS/'01-host-group-breakdown.md').write_text('\n'.join(breakdown),encoding='utf-8')
    print('Reports written to',DOCS)


if __name__=='__main__':main()
