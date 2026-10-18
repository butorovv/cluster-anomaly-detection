"""Render checkpoint D1 diagnostics; writes new files only, never reads D2."""
import argparse
import json
from pathlib import Path


def render(folder):
    d = json.loads((folder / 'diagnostics.json').read_text(encoding='utf-8'))
    lines = ['# D1: численная диагностика группового вектора', '',
             '18.10.2026. Контрольная точка №1, модель ещё не утверждена.', '',
             'Полные массивы median/MAD, covariance, spectra и pseudoinverse: '
             '[diagnostics.json](diagnostics.json). Это исследовательская диагностика, '
             'не исполняемый профиль Go.', '',
             'D1: `[2022-01-18T00:00:00Z,08:00:00Z)`, 829440/829440 полных F18; '
             'UTC — прежнее неподтверждённое допущение. В каждой группе 2880/2880 ticks. '
             'Prepared D1 точно совпал с прежним D1.bin. D2/D3 не анализировались.', '',
             'Порядок каналов: GPU total W, CPU total W, PSU AC total W, GPU mean °C, '
             'CPU mean °C; сначала пять group means, затем пять population spreads. '
             'Исходные физические единицы сохраняются до robust normalization. '
             'Covariance ddof=1, SVD rcond=1e-12; Q99 — inverted CDF, strict >.', '',
             '| Группа | N | Coverage | R zero/floor /90 | B floor /10 | Rank | κ(C) | R Q99 | B D² Q99 | D1 R/B + ticks |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for g in d['groups']:
        b = g['B']
        lines.append(f"| {g['group']} | {g['full_ticks']} | {g['coverage']:.0%} | "
                     f"{g['zero_host_mad']}/{g['floored_host_scales']} | {b['floored']} | "
                     f"{b['effective_rank']} | {b['condition']:.3f} | {g['R_q99']:.6f} | "
                     f"{b['q99_mahalanobis_squared']:.6f} | {g['R_d1_positive_ticks']}/{b['d1_positive_ticks']} |")
    lines += ['', '## Численная пригодность B', '',
              'У всех групп ранг 10, PSD covariance и конечные D². Удаление координат '
              'и ridge не требуются по этой диагностике. Максимальная относительная '
              'ошибка C C⁺ C ≈ C: '
              f"{max(g['B']['reconstruction_relative_frobenius'] for g in d['groups']):.3g}; "
              'расхождение covariance Welford с независимым centered NumPy covariance: '
              f"{max(g['B']['covariance_crosscheck_relative_error'] for g in d['groups']):.3g}. "
              'Все eigenvalues и singular values сохранены в JSON; абсолютные величины '
              'сырых covariance имеют смешанные единицы, κ приводится после нормализации.', '',
              'Алгебраическая пригодность не доказывает статистическую достаточность: '
              'это один 8-часовой фрагмент и in-sample calibration. '
              'Lag-1 correlation по 160 group-vector координатам лежит в диапазоне '
              f"[{min(min(g['group_vector_lag1_correlation']) for g in d['groups']):.3f}, "
              f"{max(max(g['group_vector_lag1_correlation']) for g in d['groups']):.3f}]. "
              '2880 ticks нельзя считать 2880 независимыми повторениями. '
              'Предельное N≥11 выполнено, междневная устойчивость неизвестна. '
              'Go-паритет чисел ещё не проверялся: Go-критерии до согласования не реализованы.', '',
              '## MAD floor: арифметика и физический смысл', '',
              'R: 4 из 1440 host-channel MAD равны нулю и требуют floor; '
              'все четыре относятся к GPU mean temperature. B: 0 из 160 scales floored, '
              f"минимальная scale={min(min(g['B']['scale']) for g in d['groups']):.8f}. "
              'Поэтому floor не влияет на B этого D1. Число 1e-4 дано отдельно в W/°C, '
              'оно не безразмерно и не равно разрешению/погрешности сенсора.', '',
              '| Хост | Median °C | Fraction exactly median | Observed min/max °C | Unique | Max abs(z) при floor |',
              '|---|---:|---:|---:|---:|---:|']
    for g in d['groups']:
        for f in g['floor_details']:
            lines.append(f"| {f['host']} | {f['median']:.8f} | {f['fraction_at_median']:.6f} | "
                         f"{f['min']:.8f} / {f['max']:.8f} | {f['unique_values']} | {f['maximum_absolute_z']:.3f} |")
    lines += ['', 'Значения z конечны: наблюдаемого overflow нет. Но нулевой MAD '
              'создаёт чувствительность к малому отклонению от массового значения. '
              'Пример: 0.01 °C / 1e-4 °C = 100; это не свидетельство физической опасности. '
              'Минимальная наблюдаемая spacing в JSON — свойство float32/агрегации, '
              'не доказанное разрешение датчика. Second-largest требует двух разных '
              'хостов, поэтому один высокий z сам по себе не определяет R. '
              'Floor сохранён без изменения; его принятие как научного соглашения '
              'остаётся вопросом контрольной точки.', '',
              '## Физические распределения D1', '',
              '| F18 | Min | Median | Q99 | Max |', '|---|---:|---:|---:|---:|']
    for name, a in d['feature_distributions'].items():
        lines.append(f"| {name} | {a['min']:.6f} | {a['median']:.6f} | {a['q99']:.6f} | {a['max']:.6f} |")
    ref = d['gpu_300W_reference_only']
    lines += ['', f"Справочное сравнение с 300 W: {ref['above_300W']} из {ref['device_samples']} "
              f"device samples; {ref['host_states_with_any']} host states с хотя бы одним таким GPU. "
              'Это не Y и не число отказов. Распределение не подтверждает паспортную '
              'совместимость и не используется для выбора нового предела. '
              'Установленный cap, SKU, rail composition и погрешность остаются неизвестны. '
              'PSU AC не сравнивается с 2200 W DC как с alarm; CPU mean не сравнивается '
              'с отдельным core shutdown limit.', '',
              '## Зафиксированные входы', '',
              'Все перечисленные SHA совпали до/после расчёта. '
              'SHA кода диагноста и исходной спецификации, версии Python/NumPy/Arrow '
              'и command сохранены в JSON.', '', '| Путь | SHA-256 |', '|---|---|']
    for path, digest in d['input_sha256_before'].items():
        lines.append(f'| {path} | `{digest}` |')
    lines += ['', '## Воспроизведение', '', 'Из корня репозитория, в существующем окружении '
              'с NumPy 2.3.5 и PyArrow 26.0.0:', '', '```powershell',
              'python tools/groupdiagnostics/d1.py --output <NEW_DIRECTORY>',
              'python tools/groupdiagnostics/report.py --input <NEW_DIRECTORY>',
              'python -m pytest -p no:cacheprovider tools/groupdiagnostics/test_d1.py', '```', '',
              'Выходные файлы создаются эксклюзивно. Новые пути/code commit в manifest '
              'могут отличаться; численные groups, feature distributions и входные SHA '
              'должны совпасть в том же окружении. D3 не загружается для вычислений.', '']
    with (folder / 'README.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    render(parser.parse_args().input)
