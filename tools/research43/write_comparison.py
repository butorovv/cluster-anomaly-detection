"""Render stage II tables and real-data plots; no calibration or model selection loop."""
import argparse
import json
import re
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from platform_info import collect

DOCS=Path('docs/research-4.3')
METHODS=['A0 historical','A0 D1-Q99','B1 / H1 context','B2','Power','H2+','H2-','H2 any']


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |',
                     *['| '+' | '.join(str(v) for v in row)+' |' for row in rows]])+'\n'


def fmt(x):return f'{x:.6g}' if x is not None else '—'
def pct(a,b):return f'{100*a/b:.2f}%' if b else 'не оценивается'
def rate(x):return f'{100*x:.2f}%' if x is not None else 'не оценивается'
def interval(ci):return '['+', '.join(f'{100*v:.2f}' for v in ci)+']' if ci is not None else '—'


def prose_spacing(text):
    return re.sub(r'(?<=\d)(?=[А-Яа-яЁё])',' ',re.sub(r'([А-Яа-яЁё])(?=\d)',r'\1 ',text))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=Path('results/research43-stage2-v1'))
    args=p.parse_args();s=json.loads((args.output/'summary.json').read_text());a=json.loads((args.output/'audit.json').read_text())
    forest=json.loads((args.output/'forest-benchmark.json').read_text())
    platform_path=args.output/'platform.json'
    if platform_path.exists():platform=json.loads(platform_path.read_text())
    else:
        platform=collect();platform_path.write_text(json.dumps(platform,indent=2),encoding='utf-8')
    hp2=json.loads((args.output/'H2-profile.json').read_text());ev=s['comparisons'];full=s['methods'];echo=a['temporal_echo']
    paths=DOCS/'figures/stage2';paths.mkdir(parents=True,exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(12,4))
    axes[0].bar(['A0 hist','A0 Q99','B1/H1','B2','Power','H2+','H2-','H2 any'],[full[n]['signals'] for n in METHODS])
    axes[0].tick_params(axis='x',rotation=30);axes[0].set_ylabel('D2 signal states');axes[0].set_title('D1-calibrated thresholds')
    selected=METHODS[2:];axes[1].bar(['B1/H1','B2','Power','H2+','H2-','H2 any'],[full[n]['within_pairs']['ratio'] for n in selected])
    axes[1].axhline(1,color='black',linestyle=':');axes[1].set_ylabel('within pairs / exact random expectation');axes[1].set_title('Topology specificity, descriptive')
    fig.tight_layout();fig.savefig(paths/'full-d2-comparison.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4));selected=['B1 / H1 context','B2','Power','H2 any']
    for ax,tag in zip(axes,['risk','shared_risk']):
        rr=[ev['all'][n]['120s'][tag] for n in selected];x=np.arange(4)
        ax.bar(x-.17,[100*r['event_rate'] for r in rr],.34,label='transition');ax.bar(x+.17,[100*r['control_rate'] for r in rr],.34,label='control')
        ax.set_xticks(x,['B1/H1','B2','Power','H2 any']);ax.set_ylabel('fresh onset / eligible pairs, %');ax.set_title(tag);ax.legend()
        for i,r in enumerate(rr):ax.text(i,max(r['event_rate'],r['control_rate'])*100+1,f"n={r['n']}",ha='center',fontsize=8)
        ax.set_ylim(0,110)
    fig.tight_layout();fig.savefig(paths/'risk-set-comparison.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4));fracs=list(s['budget'])
    for name in ['B1 / H1 context','B2','Power','H2 any']:
        axes[0].plot([float(f)*100 for f in fracs],[s['budget'][f][name]['summary']['within_pairs']['ratio'] for f in fracs],'o-',label=name)
        axes[1].plot([float(f)*100 for f in fracs],[100*s['budget'][f][name]['event']['all']['risk']['host_ci']['difference'] for f in fracs],'o-',label=name)
    axes[0].set_ylabel('within pairs / random expectation');axes[1].set_ylabel('transition minus control fresh onset, pp')
    for ax in axes:ax.set_xlabel('common-valid D2 top-K budget, %');ax.legend(fontsize=8);ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(paths/'equal-budget.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4));x=np.arange(8)
    for i,name in enumerate(['B1 / H1 context','B2','Power','H2 any']):
        ax.bar(x+(i-1.5)*.18,full[name]['hour_signals'],.18,label=name)
    ax.set_xticks(x,[f'{8+i:02}:00' for i in range(8)]);ax.set_ylabel('signal states per hour');ax.legend();ax.set_title('Real D2 time concentration (assumed UTC)')
    fig.tight_layout();fig.savefig(paths/'hour-concentration.png',dpi=150);plt.close(fig)
    # Earliest real positive onset with a negative signal exactly 60s earlier.
    masks=np.load(args.output/'masks.npz')['masks'];positive=masks[5];negative=masks[6]
    start=np.zeros_like(positive);start[1:]=positive[1:]&~positive[:-1]
    candidates=np.argwhere(start[6:]&negative[:-6]);t,h=map(int,candidates[0]);t+=6
    channels=np.load(args.output/'channels.npz')
    dtype=np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),('features','<f8',(18,)),('scores','<f8',(6,)),('distance','<f8')])
    d2=np.memmap('results/context-v1/D2.bin',mode='r',dtype=dtype);raw=d2['features'].reshape(2880,288,18)
    psu=raw[:,:,0]+raw[:,:,1];delta=np.full(psu.shape,np.nan);delta[6:]=psu[6:]-psu[:-6]
    lo=max(0,t-18);hi=min(2880,t+25);seconds=(np.arange(lo,hi)-t)*10
    fig,axes=plt.subplots(3,1,figsize=(10,7),sharex=True)
    axes[0].plot(seconds,psu[lo:hi,h],label='real PSU power');axes[0].set_ylabel('W')
    axes[1].plot(seconds,delta[lo:hi,h],label='delta60 PSU');axes[1].set_ylabel('W')
    for key,color,threshold in [('positive','C0','positive_threshold'),('negative','C1','negative_threshold')]:
        axes[2].plot(seconds,channels[key][lo:hi,h],color=color,label='H2 '+key)
        axes[2].axhline(hp2[threshold],color=color,linestyle='--')
    axes[2].set_ylabel('normalized change');axes[2].set_xlabel('seconds from positive H2 onset')
    for ax in axes:ax.axvline(-60,color='black',linestyle=':');ax.axvline(0,color='black',linestyle=':');ax.legend();ax.grid(alpha=.2)
    host=hp2['hosts'][h];timestamp=str(np.datetime64(int(d2['timestamp'].reshape(2880,288)[t,h]),'us'))
    fig.suptitle(f'{host} {timestamp}: real lag-60 echo example');fig.tight_layout();fig.savefig(paths/'real-echo.png',dpi=150);plt.close(fig)
    shared=[ev['all'][n]['120s']['shared_risk'] for n in selected]
    main_doc=['# Этап II: сравнение H1/H2 и контрольных вариантов\n',
        '**Рекомендация: использовать H1 с контекстным B1 как минимальную основу дальнейшего '
        'согласования локальной статистической оценки; H2 в основной локальный и групповой '
        'алгоритм сейчас не включать.** B2 остаётся содержательным исследовательским '
        'альтернативным вариантом. H1 не новый обученный детектор, а раздельное представление '
        'существующих A0/B1. Общего доказательства превосходства по аппаратным отказам нет.\n',
        'Дата 14.10.2026. Разрешение пользователя: H1 утверждён, один H2 экспериментален, '
        'H3 условен. [Исходные формулы](02-hypotheses-protocol.md), '
        '[дополнение оценки до расчёта](02-evaluation-protocol.md). D1=[00:00,08:00), '
        'D2=[08:00,16:00) 18.01.2022, assumed UTC, по829440 состояний/288 хостов. '
        'D3 не использован; реальные пропуски по этому полностью доступному дню не изучены. '
        'Первые1728 состояний для Δ60 undefined: H2/Power знаменатель827712. '
        'Рабочие thresholds только D1; D2 повторно исследовательский, не независимая валидация.\n',
        '## 1. Реализованные определения и что сохраняет H1\n',
        r'$$s_{abs}(h,t)=IF_{A0}(z_h(t)),\quad A_{abs}=\mathbf1[s_{abs}>Q_{.99,D1}(s_{abs})],$$' '\n'
        r'$$\theta_h=Q_{.99,D1}(s_{abs}(h,\cdot)),\quad A_{ctx}=\mathbf1[s_{abs}>\theta_h].$$' '\n',
        'Оригинальный score сохранён побитно; A_ctx совпадает с B1 по всем829440 '
        'строкам. H1 выдаёт `(score_abs,A_abs,A_ctx,margin)` отдельно. В групповую '
        'диагностику H1 передаётся только A_ctx; никакого OR, переобучения или объявления '
        'крайних хостов исправными. Абсолютный канал сохраняет редкость относительно '
        'популяции, контекстный отвечает, изменилось ли положение score относительно D1 '
        'данного хоста. Даже A_ctx не доказывает физическое изменение или отказ.\n',
        table(['Host','Absolute score median','D1 host theta','A_abs states/rate','A_ctx states/rate','H2+/- states'],[
            [r['host'],fmt(r['absolute']['q50']),fmt(r['host_threshold']),str(r['absolute_flag_states'])+'/'+pct(r['absolute_flag_states'],2880),
             str(r['context_states'])+'/'+pct(r['context_states'],2880),f"{r['H2plus_states']}/{r['H2minus_states']}"] for r in s['four_hosts']]),
        'Три a02 сохраняют абсолютные сигналы в большинстве состояний; a02n11 '
        'сохраняет высокий количественный score, хотя глобальный Q99 не отмечает '
        'большую часть его состояний. Контекстные частоты четырёх —59/77/39/60 '
        'состояний (235 всего), без постоянного бинарного вклада. H1 семантически '
        'полезен и технически проверен; улучшение независимой точности не заявляется.\n',
        '## 2. Единственный вариант H2: результат калибровки\n',
        r'$$\Delta P_{h,j}(t)=P_{h,j}(t)-P_{h,j}(t-60s),\quad '
        r'u_{h,j}=\frac{\Delta P_{h,j}-b_{h,j}}{\max(1.4826MAD_{h,j},\epsilon_j)},$$' '\n'
        r'$$\epsilon_j=\max(1W,Q_{.50,D1,all\ hosts}|\Delta P_j|),\quad '
        r'u_h^+=\max_j\max(u_{h,j},0),\quad u_h^-=\max_j\max(-u_{h,j},0).$$' '\n',
        'Строгие сигналы `u+>theta+`, `u−>theta−`, pooled D1 Q99.5. '
        f"theta+={hp2['positive_threshold']:.12g}, theta−={hp2['negative_threshold']:.12g}; "
        'epsilon GPU/CPU/PSU='+ '/'.join(fmt(x) for x in hp2['epsilon'])+' W. '
        'Host median/MAD обучены только на D1. Масштабы, лаг и thresholds не менялись. '
        'H2 any в таблицах — лишь объединение двух направлений H2 для диагностики, '
        'не объединение с IF и не окончательный LocalResult.\n',
        table(['Координата','Scale min/median/max, W','Макс u+ D2','Макс u− D2','D2 превышений +/−','Хостов с MAD floor'],[
            [c,'/'.join(fmt(r['scale'][k]) for k in ['min','q50','max']),fmt(r['max_u_positive']),fmt(r['max_u_negative']),
             f"{r['positive_exceedances']}/{r['negative_exceedances']}",r['floor_hosts']] for c,r in a['coordinate_audit'].items()]),
        '**Все6012 положительных и5895 отрицательных сигналов определяются PSU.** '
        'GPU/CPU не пересекают общие thresholds: их максимальные нормированные '
        'оценки ниже25.5. Так фиксированное многокомпонентное max/Q99.5 оказалось '
        'практически каналом PSU в D2. Причина подтверждается формулами и диапазонами '
        'score, а не является предположением о программной ошибке. Не исправляли '
        'это новыми порогами, отдельными компонентными квантилями или другими лагами.\n',
        '## 3. Полное D2: частоты, длительности, концентрация\n',
        table(['Метод','Signals/valid rate','Runs','Duration median/q95/max,s','4a02 states','Top4 share','Pair ratio','New-onset pair ratio'],[
            [n,str(r['signals'])+'/'+pct(r['signals'],r['valid_states']),r['runs'],
             '/'.join(fmt(r['duration'][k]) for k in ['q50','q95','max']),r['four_signals'],rate(r['top4_share']),
             fmt(r['within_pairs']['ratio']),fmt(r['onset_pairs']['ratio'])] for n,r in full.items()]),
        '![Полное D2 и топология](figures/stage2/full-d2-comparison.png)\n',
        '![Часовая концентрация](figures/stage2/hour-concentration.png)\n',
        'A0 Q99 сохраняет длительные состояния четырёх a02 (max28800с); '
        'контекстный H1/B1 не возвращает этот постоянный бинарный эффект. '
        'Для H2 median10с, max60с: нельзя интерпретировать11907 строк как11907 '
        'независимых событий. Даже9761 runs не являются независимыми отказами '
        'из-за повторов одного хоста, общего времени и lag-эхо. Полная разбивка '
        'по288 хостам/16 группам сохранена в JSON и приложении таблиц.\n',
        '## 4. Переходы, контроли и одинаковый risk set\n',
        'Сохранены6978 прежних событий,6050 пар и928 unmatched, без отбора '
        'по score и повторного matching. Primary fresh onset — false→true '
        'в [t,t+120], pre60 без данного сигнала. Separate already-active, '
        'preexisting, all-post-onset и continuous-only приведены в '
        '[полных таблицах](02-evaluation-tables.md). Primary этапа I воспроизведён точно.\n',
        table(['Метод','Fresh/all6978','Primary event/control, N6050','Own risk N','Own risk event/control','Shared risk N3067 event/control'],[
            [n,pct(ev['all'][n]['120s']['fresh'],6978),rate(ev['all'][n]['120s']['primary']['event_rate'])+'/'+rate(ev['all'][n]['120s']['primary']['control_rate']),
             ev['all'][n]['120s']['risk']['n'],rate(ev['all'][n]['120s']['risk']['event_rate'])+'/'+rate(ev['all'][n]['120s']['risk']['control_rate']),
             rate(ev['all'][n]['120s']['shared_risk']['event_rate'])+'/'+rate(ev['all'][n]['120s']['shared_risk']['control_rate'])] for n in METHODS]),
        'Own risk: обе стороны без соответствующего pre60-сигнала; знаменатель '
        'зависит от метода. Shared risk — пересечение B1/B2/Power/H2 any (3067 '
        'пар), поэтому проценты этих четырёх методов можно непосредственно '
        'сопоставлять на одной выборке. Primary и own-risk проценты по разным '
        'методам сами по себе не являются честным сравнением одинаковой популяции.\n',
        table(['Категория','Метод','Primary N/event/control','Own risk N/event/control','Shared risk N/event/control'],[
            [cat,n,*[f"{r[tag]['n']}/{r[tag]['event']}/{r[tag]['control']}" for tag in ['primary','risk','shared_risk']]]
            for cat,methods in ev.items() if cat!='all' for n in ['B1 / H1 context','B2','Power','H2+','H2-','H2 any']
            for r in [methods[n]['120s']]]),
        '**Для PSU rise у B2 own-risk N=0, общий risk set также пуст.** '
        'Нельзя объявить нулевую вероятность нового сигнала по отсутствующей '
        'выборке. H2+ отмечает673/724 таких переходов, но это не доказательство '
        'улучшения: см. эффект лага ниже. Для Power event100%/control0% '
        'на risk sets возникает по конструкции отбора переходов и контроля; '
        'даже вырожденный bootstrap CI[100,100] не означает идеальный детектор отказов.\n',
        '![Risk set](figures/stage2/risk-set-comparison.png)\n',
        table(['Метод (shared3067)','Δ event−control,п.п.','CI host','CI hour','CI halfhour'],[
            [n,fmt(100*r['host_ci']['difference']),interval(r['host_ci']['interval95']),interval(r['hour_ci']['interval95']),interval(r['halfhour_ci']['interval95'])]
            for n,r in zip(selected,shared)]),
        'CI — описательные percentile bootstrap1999, seed4301, whole host '
        'и общие часы (8 блоков),30мин sensitivity. Не IID строк; host-only '
        'и time-only варианты не являются полным двухсторонним cluster-robust '
        'доказательством. Нет множественных подтверждающих p-values для risk '
        'таблиц; нет независимых отрицательных меток и нет precision/F1 отказов.\n',
        '## 5. Качество matching и928 unmatched\n',
        'Относительное расхождение определяется по прежней мощности доминирующей '
        'подсистемы; median='+rate(s['matching']['quality']['q50'])+', q95='+rate(s['matching']['quality']['q95'])+'. '
        'Страты: '+', '.join(f'{k}: {v}' for k,v in s['matching']['strata'].items() if k!='all')+'. '
        'Primary6050 не фильтровался по этим стратам. Полные таблицы primary/risk '
        'по качеству и категориям представлены в приложении; >5% содержит всего25 '
        'пар и непригоден для устойчивого отдельного вывода.\n',
        table(['Категория','Matched/Unmatched N','|Δ| median matched/unmatched,W','Pre P median matched/unmatched,W','t−start q95 matched/unmatched,s'],[
            [cat,f"{r['matched']['n']}/{r['unmatched']['n']}",
             '/'.join(fmt(r[tag]['abs_delta']['q50']) for tag in ['matched','unmatched']),
             '/'.join(fmt(r[tag]['pre_power']['q50']) for tag in ['matched','unmatched']),
             '/'.join(fmt(r[tag]['representative_delay']['q95']) for tag in ['matched','unmatched'])]
            for cat,r in s['matched_unmatched'].items()]),
        'У unmatched средние |Δ|415.66 против370.47W в pooled смешанной '
        'выборке; состав подсистем влияет на эту величину, поэтому важны строки '
        'по категориям. Например GPU rise pre median669.20 против765.63W, '
        'amplitude median677.80 против637W. Распределения не идентичны; '
        'paired результат нельзя безоговорочно переносить на все6978 событий. '
        'Числа fresh для unmatched каждого метода также приведены отдельно.\n',
        '## 6. Дополнительная информация H2 и временное эхо\n',
        f"H2/Power intersection={s['overlap']['H2 any']['Power']['intersection']}, "
        f"Jaccard={s['overlap']['H2 any']['Power']['jaccard']:.6f}. "
        'H2-only3913 состояния, Power-only14182. Поэтому буквальная гипотеза '
        'полного дублирования опровергнута. Все H2-only — PSU; '
        'median max|Δ|/Power-threshold='+fmt(a['novel']['H2_only_raw_power_ratio']['q50'])+', '
        'то есть в основном изменения меньшей амплитуды близко к прежнему порогу. '
        'Из3913 лишь870 совпадают с B1 и1780 с B2. Наличие новых строк '
        'не доказывает их эксплуатационной полезности.\n',
        'H2-only within/random ratio='+fmt(a['novel']['H2_only']['ratio'])+' '
        '(описательно, без дополнительного подтверждающего семейства). '
        'Это дополнительная топологически согласованная информация о PSU '
        'при выбранной нормировке. Она ещё не является групповым аномальным '
        'состоянием, качеством обнаружения отказа или доказательством нормального job completion.\n',
        f"Из{echo['positive_onsets']} новых H2+ runs у{echo['positive_onsets_with_negative_60s_before']} "
        f"({pct(echo['positive_onsets_with_negative_60s_before'],echo['positive_onsets'])}) есть H2− ровно60с ранее. "
        'Для H2+ medianΔ60 PSU='+fmt(echo['positive_PSU_delta60']['q50'])+'W, '
        'а median фактического изменения между соседними10с наблюдениями='
        +fmt(echo['positive_PSU_adjacent_change']['q50'])+'W. Median |adjacent|/|Δ60|='
        +fmt(echo['positive_adjacent_over_delta60']['q50'])+'. '
        'Это наблюдаемое lag-эхо: положительное приращение может возникнуть '
        'из-за малого значения P(t−60), хотя текущая мощность почти не меняется. '
        'Соседние изменения использованы только как описание реальной траектории, '
        'не как второй лаг или новый кандидат H2.\n',
        f'![Реальный пример эха](figures/stage2/real-echo.png)\n\n'
        f'Пример выбран автоматически: первый H2+ onset с H2−60с ранее, {host}, {timestamp}. '
        'Без ручного отбора и синтетических значений.\n',
        '**Не считать отрицательный и положительный отклики лагового оператора '
        'двумя независимыми неисправностями или реальными переключениями нагрузки.** '
        'Изменение мощности, статистическая нетипичность и подтверждённый отказ '
        'сохраняют разные определения. Ни обычность нагрузки, ни отказ без '
        'внешних журналов здесь не подтверждены.\n',
        '## 7. Внутригрупповая и общекластерная активность\n',
        table(['Метод','Within/cross pairs','Signal/onset ratio к случайным','Holm16 signal/onset p','Localized support states','New localized onset states','All16 groups active timestamps'],[
            [n,f"{r['within_pairs']['within']}/{r['within_pairs']['cross']}",
             fmt(r['within_pairs']['ratio'])+'/'+fmt(r['onset_pairs']['ratio']),
             fmt(r['permutation']['signal_pairs']['p_holm16'])+'/'+fmt(r['permutation']['onset_pairs']['p_holm16']),
             r['localized_group_states'],r['new_localized_group_states'],r['all_groups_active_timestamps']] for n,r in full.items()]),
        r'$$S_g=K_g/N_g,\quad E_g=S_g-S_{\neg g}.$$'
        '\n\nДиагностическое localized state: K_g≥2 и E_g>0; '
        'новое синхронное изменение — минимум2 onset и положительный '
        'onset-контраст. Длительности и распределения S/E в приложении. '
        'Это не окончательный GroupEvent и не калибровка рабочего группового порога. '
        'Отсутствующая доступность имеет undefined S/E; реальные missing data '
        'здесь отсутствуют, корректность проверена отдельными fixtures.\n',
        '1999 общих перестановок хостов по18, seed4202; ряды, частоты, общая '
        'активность сохранены. Семейство8 методов×2 статистики=16, Holm. '
        'Signal draws A0/B1/B2 совпали с прежними сохранёнными draws №4.2: '
        'новое вычисление не создаёт нового независимого реального испытания. '
        'Pair ratio A0 завышен четырьмя устойчивыми a02: высокая статистическая '
        'локализация не равнозначна временному групповому событию. '
        'H2 ratio≈2.59 превосходит Power≈1.66 в этой выборке, но реагирует '
        'только на PSU и лаговое эхо. Поэтому H2 не выбран для основной '
        'групповой агрегации. Перспектива — исследовать S/E от A_ctx '
        'с отдельным абсолютным контекстом, после нового согласования.\n',
        '## 8. Равный бюджет и устойчивость\n',
        'Общий eligible набор827712 определённых Δ60 D2; бюджеты0.5/1/2% '
        'дают4138/8277/16554 состояний. B1 ранжируется по margin к hostθ, '
        'B2 по score, Power по нормированному приращению, H2 по max(u+,u−). '
        'Stable ties сохраняют порядок timestamp/host. Это исследовательский '
        'top-K, **не рабочие пороги D2**. Own-risk sets опять могут различаться.\n',
        table(['Бюджет','Метод','N signals','Pair ratio','Own risk N','Event/control new120','Δ,п.п.'],[
            [rate(float(f)),n,r['summary']['signals'],fmt(r['summary']['within_pairs']['ratio']),r['event']['all']['risk']['n'],
             rate(r['event']['all']['risk']['event_rate'])+'/'+rate(r['event']['all']['risk']['control_rate']),
             fmt(100*r['event']['all']['risk']['host_ci']['difference'])]
            for f,methods in s['budget'].items() for n,r in methods.items()]),
        '![Равный бюджет](figures/stage2/equal-budget.png)\n',
        'Топологическое отношение зависит от бюджета: H2≈3.09/2.95/2.27; '
        'B2≈3.08/2.50/2.03; B1≈1.89/2.05/1.93. Это не универсальная '
        'победа H2: разные физические состояния, lag-эхо и разные risk sets. '
        'Не выбирали вариант по одному показателю или F1_ref.\n',
        table(['Seed','Метод','Signals','Fresh120/all','Pair ratio'],[
            [seed,n,r['signals'],pct(r['fresh']['all'],6978),fmt(r['pairs']['ratio'])]
            for seed,methods in s['seed_results'].items() for n,r in methods.items()]),
        'Seeds42/43/44 — ранее сохранённые парные леса, без переобучения; '
        'H1/H2/Power детерминированы. Статистическое преимущество B2 на '
        'переходах сохраняется описательно, но систематическая rise-асимметрия '
        'и отсутствие независимой разметки остаются. Восемь часовых блоков '
        'и один день ограничивают устойчивость вывода.\n',
        '## 9. Вычислительные затраты и воспроизводимость\n',
        f"Платформа: {s['platform']}; {platform['cpu']}, {platform['logical_processors']} logical processors, "
        f"RAM={fmt(platform['RAM_bytes']/2**30) if platform['RAM_bytes'] is not None else 'unavailable'}GiB. Go {forest['go_version']}, GOMAXPROCS=1; NumPy OPENBLAS_NUM_THREADS=1. "
        'Один прогрев и5 последовательных повторов. CPU/RAM получены registry/WinAPI; '
        'CIM в sandbox недоступен.\n',
        table(['Расчёт полного D2/D1','Median,s','Min/max,s','Комментарий'],[
            ['A0 saved forest D2 score',fmt(forest['models']['A0']['median']),fmt(forest['models']['A0']['min'])+'/'+fmt(forest['models']['A0']['max']),'нормализация, score и проверка expected; no fit'],
            ['B2 saved forest D2 score',fmt(forest['models']['B2']['median']),fmt(forest['models']['B2']['min'])+'/'+fmt(forest['models']['B2']['max']),'включает host adaptation; no fit'],
            *[[n,fmt(r['median']),fmt(r['minimum'])+'/'+fmt(r['maximum']),'Python; cached IF score or precomputed delta as named'] for n,r in s['benchmark'].items()]]),
        'H1 дополнительных деревьев не обучает; получение abs score имеет '
        'стоимость A0. H1 profile — '+str((args.output/'H1-profile.json').stat().st_size)+' bytes; '
        'H2 profile — '+str((args.output/'H2-profile.json').stat().st_size)+' bytes. '
        f"Python peak working set={s['peak_working_set_bytes']/2**20:.1f}MiB; это весь research-процесс "
        '(включая JSON, memmaps, результаты и bootstrap), не отдельная модель. '
        f"Go reserved Sys={forest['go_reserved_bytes']/2**20:.1f}MiB — не peak RSS. "
        f"Input/hash/load={s['input_io_seconds']:.3f}s; preprocessing={s['preprocessing_seconds']:.3f}s; "
        f"profiles fit={s['fit_seconds']:.3f}s; apply={s['application_seconds']:.3f}s; "
        f"initial NPZ writing={s['writing_seconds']:.3f}s; полный research={s['elapsed_seconds']:.2f}s. "
        'Эти тайминги не являются масштабированием VI; повторения scoring были '
        'в одном последовательном порядке, без рандомизации A0/B2. Разница их '
        'нескольких процентов не объявляется преимуществом производительности.\n',
        'Сложность: H1 threshold nearest-rank O(N) expected / O(NlogN) при '
        'сортировке; margin/flags O(N), хранение O(H) сверх исходного IF. '
        'H2 fixed3 coordinates/lag: O(N), профиль O(3H), потоковый буфер '
        'O(6·3H); основной offline audit хранит массивы O(N). Групповая '
        'агрегация O(N+LG). IF scoring O(NTd), norm O(NF). Без нового '
        'эмпирического бенчмарка обучения IF по этим измерениям нельзя '
        'оценить полную цену переобучения B2.\n',
        table(['Артефакт','SHA256'],[[k,v] for k,v in s['profile_hashes'].items()]),
        '[Все SHA входов](02-evaluation-tables.md), '
        '[команды](../../tools/research43/README.md), '
        '[фактические проверки](02-CHECKS.md). Независимый audit: точные '
        'H1/H2 параметры и все определённые score;416896 temporal checks; '
        '80 direct permutation counts; Holm16;15 lexsort budget checks. '
        'Новый Go benchmark повторно вычислил A0/B2 по всему D2, max error0. '
        'Основные профили, F18, production, PostgreSQL, Kafka, архитектура и РПЗ не изменены.\n',
        '## 10. Ответы и решение контрольной точки №3\n',
        '1. **Что улучшилось:** H1 сохраняет абсолютную редкость и индивидуальную '
        'интерпретацию без изменения score/B1. Исправлена оценка risk sets и '
        'отдельно раскрыты качество matching и unmatched. H2 даёт дополнительные '
        'PSU изменения ниже прежнего абсолютного порога и их топологическую '
        'согласованность. Это новые диагностические свойства, не доказанная '
        'точность обнаружения аппаратных неисправностей.\n'
        '2. **Что осталось:** D2 reuse, одна assumed UTC дата, непроверенная '
        'физическая топология, зависимые/перекрывающиеся переходы, несопоставленные '
        'окна, пустые risk sets, отсутствие эксплуатационной разметки. '
        'IF не обязан сигнализировать каждое изменение мощности.\n'
        '3. **Польза H2 сверх простого порога:** буквальное дублирование отвергнуто; '
        'проверенная добавка —3913 PSU состояний и ratio3.10 для этой разности. '
        'Однако GPU/CPU канал подавлен общим threshold, около89% новых H2+ '
        'имеют отрицательный отклик60с ранее. Практическое улучшение основной '
        'методики не подтверждено.\n'
        '4. **H2 для групповой агрегации:** сейчас не включать. Более высокий '
        'pair ratio не устраняет подмену групповой аномалии синхронным '
        'изменением/эхом PSU. Сохранить отдельно исследовательскую диагностику, '
        'без LocalResult/GroupEvent и без OR с H1.\n'
        '5. **H1+B1 или более сложное:** H1+B1 — минимальная обоснованная '
        'основа локальной статистической оценки для следующего согласования. '
        'B2 лучше согласуется с частью переходов и имеет больший pair ratio, '
        'но не доказана его универсальная практическая необходимость. '
        'Окончательную локальную модель и рабочий групповой критерий пока не '
        'зафиксировали; дальнейшие этапы требуют нового разрешения.\n'
        '6. **Формулы для будущей РПЗ:** сохранить F18/global normalization/IF; '
        'добавить раздельные s_abs,A_abs,theta_h,A_ctx и margin; явно определить '
        'статистическую нетипичность, изменение режима и подтверждённый отказ. '
        'S_g,E_g с фактической доступностью — основа последующей спецификации, '
        'не окончательные пороги. H2 представить как эксперимент с отрицательным '
        'результатом основной интеграции и правилом лагового эха. Не добавлять '
        'H2 в утверждённый детектор автоматически; РПЗ сейчас не редактируется.\n'
        '7. **Гипотезы:** H1 техническое/семантическое разделение подтверждено; '
        'его независимое улучшение качества отказов не проверено. H2 '
        'вычислительная реализуемость и дополнительная PSU-информация '
        'подтверждены; полное дублирование отвергнуто; польза как общего '
        'трёхподсистемного канала аномалий и основания основной групповой '
        'интеграции не подтверждены. H3 не реализована, не проверена и '
        'остаётся условной до отдельного согласования после III.\n',
        '**Остановка после этапа II.** Этап III, физическая доработка, '
        'окончательный GroupEvent и D3 не начаты. Ветка исследования основана '
        'на этапе I; при будущей интеграции №4.1→№4.2→№4.3 использовать '
        'один tracked набор statistical helpers, новые копии зависимости '
        'не добавлены. Merge самостоятельно не выполняется.\n']
    (DOCS/'02-model-comparison.md').write_text(prose_spacing('\n'.join(main_doc)),encoding='utf-8')
    appendix=['# Полные таблицы оценки этапа II\n','Только диагностические/исследовательские показатели, не разметка отказов.\n',
              '## SHA входов\n',table(['Path','SHA256'],[[k,v] for k,v in s['hashes_before_after'].items()])]
    for cat,methods in ev.items():
        appendix.extend([f'## {cat}: все окна, прежние и новые сигналы\n',table(['Method','Window','N','Any','Pre60','Active before','Post-onset','Fresh','Continuous only/known','Latency q50/q95','Duration q50/q95'],[
            [n,w,r['n'],r['any'],r['pre60'],r['active_before'],r['onset'],r['fresh'],f"{r['continuous_only']}/{r['continuous_known']}",
             '/'.join(fmt(r['latency'].get(k)) for k in ['q50','q95']),'/'.join(fmt(r['duration'].get(k)) for k in ['q50','q95'])]
            for n,windows in methods.items() for w,r in windows.items()])])
        appendix.extend([f'## {cat}: risk sets и неопределённость120s\n',table(['Method','Set','N','Event','Control','Δ pp','CI host','CI hour','CI halfhour'],[
            [n,tag,r['n'],r['event'],r['control'],fmt(100*r['host_ci']['difference']) if r['n'] else '—',
             interval(r['host_ci']['interval95']),interval(r['hour_ci']['interval95']),interval(r['halfhour_ci']['interval95'])]
            for n,windows in methods.items() for tag in ['primary','risk','shared_risk'] for r in [windows['120s'][tag]]])])
        appendix.extend([f'## {cat}: matching quality120s\n',table(['Method','Quality','Set','N','Event/control rate','Δ pp','CI host','CI hour'],[
            [n,q,tag,r['n'],rate(r['event_rate'])+'/'+rate(r['control_rate']),fmt(100*r['host_ci']['difference']) if r['n'] else '—',
             interval(r['host_ci']['interval95']),interval(r['hour_ci']['interval95'])]
            for n,windows in methods.items() for q,qs in windows['120s']['quality'].items() for tag,r in qs.items()])])
        appendix.extend([f'## {cat}: unmatched928, without a control\n',table(['Method','N','Fresh120','Pre60'],[
            [n,*[windows['120s']['unmatched'][k] for k in ['n','fresh','pre60']]] for n,windows in methods.items()])])
    appendix.extend(['## Групповая и общекластерная активность\n',table(['Method','Cluster K q50/q95/max active','Active groups q50/q95/max','S q95/max','E q95/max','Localized run q50/q95/max'],[
        [n,'/'.join(fmt(r['active_cluster_activity'].get(k)) for k in ['q50','q95','max']),
         '/'.join(fmt(r['active_groups'].get(k)) for k in ['q50','q95','max']),'/'.join(fmt(r['S'].get(k)) for k in ['q95','max']),
         '/'.join(fmt(r['E'].get(k)) for k in ['q95','max']),'/'.join(fmt(r['localized_group_run_duration'].get(k)) for k in ['q50','q95','max'])] for n,r in full.items()]),
        '## Вклад четырёх a02 в пары\n',table(['Method','All within pairs','Four contribution','Without four ratio'],[
            [n,r['within_pairs']['within'],r['four_pair_contribution'],fmt(r['without_four_pairs']['ratio'])] for n,r in full.items()]),
        '## Все хосты, counts by method\n',table(['Host',*METHODS],[[h,*[full[n]['per_host_signals'][i] for n in METHODS]] for i,h in enumerate(hp2['hosts'])]),
        '## Все группы, counts by method\n',table(['Group',*METHODS],[[f'a{i+1:02}',*[full[n]['per_group_signals'][i] for n in METHODS]] for i in range(16)])])
    (DOCS/'02-evaluation-tables.md').write_text(prose_spacing('\n'.join(appendix)),encoding='utf-8')
    print('Stage II report and tables written; plots at',paths)


if __name__=='__main__':main()
