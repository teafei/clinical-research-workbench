"""Explicit quality gates, encounter-level cohort selection and descriptive statistics."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import re
import unicodedata
import pandas as pd
from .data import Bundle, DIAGNOSES, PROCEDURES
from . import __version__

MISSING = {'', 'na', 'n/a', 'null', 'none', 'nan', '未知', '未查', '不详'}
DATE_PATTERN = re.compile(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?$')
ISSUE_COLUMNS = ['table', 'source_row', 'record_id', 'column', 'severity', 'code', 'message', 'source_value']


def string(value):
    return '' if pd.isna(value) else str(value)


def clean_text(value):
    value = unicodedata.normalize('NFKC', string(value)).strip()
    return pd.NA if value.lower() in MISSING else value


@dataclass
class Prepared:
    bundle: Bundle
    tables: dict[str, pd.DataFrame]
    issues: pd.DataFrame
    usable_encounters: pd.DataFrame
    usable_labs: pd.DataFrame
    audit: list[dict]


def prepare(bundle: Bundle) -> Prepared:
    tables, issues, audit = {}, [], []
    for flag in bundle.source_warnings:
        issues.append({'table': 'source', 'source_row': 0, 'record_id': '', 'column': '', 'severity': 'warning',
                       'code': 'SOURCE:' + flag['code'], 'message': flag['message'], 'source_value': str(flag['count'])})
    for name, raw in bundle.tables.items():
        frame = raw.copy(deep=True)
        for col in frame:
            frame[col] = frame[col].map(clean_text).astype('string')
        frame['_source_row'] = range(2, len(frame) + 2)
        frame['_eligible'] = True
        tables[name] = frame
        audit.append({'step': 'normalize_text', 'table': name, 'rows': len(frame), 'source_hash': bundle.source_hashes[name]})

    def issue(table, i, column, severity, code, message, block=False):
        frame = tables[table]
        key = {'patients': 'patient_id', 'encounters': 'encounter_id', 'labs': 'result_id'}[table]
        issues.append({'table': table, 'source_row': int(frame.at[i, '_source_row']), 'record_id': string(frame.at[i, key]),
                       'column': column, 'severity': severity, 'code': code, 'message': message,
                       'source_value': string(bundle.tables[table].at[i, column])[:160]})
        if block:
            frame.at[i, '_eligible'] = False

    for table, key in [('patients', 'patient_id'), ('encounters', 'encounter_id'), ('labs', 'result_id')]:
        f = tables[table]
        for i in f.index[f[key].isna()]:
            issue(table, i, key, 'error', 'MISSING_KEY', '主键为空，保留原行并排除分析。', True)
        duplicate = f[key].notna() & f[key].duplicated(keep=False)
        for i in f.index[duplicate]:
            issue(table, i, key, 'error', 'DUPLICATE_KEY', '主键重复，整组排除，需在来源数据核实。', True)

    patients, enc, labs = tables['patients'], tables['encounters'], tables['labs']
    sex_alias = {'男': 'M', '女': 'F', 'male': 'M', 'female': 'F', 'm': 'M', 'f': 'F', 'M': 'M', 'F': 'F', 'U': 'U'}
    patients['sex'] = patients['sex'].map(lambda v: sex_alias.get(string(v), 'U')).astype('string')
    for i in patients.index[patients['sex'].eq('U')]:
        issue('patients', i, 'sex', 'warning', 'SEX_UNKNOWN', '性别未知；不推断为任何已知类别。')
    valid_patients = set(patients.loc[patients['_eligible'], 'patient_id'].dropna())
    for i in enc.index[~enc['patient_id'].isin(valid_patients)]:
        issue('encounters', i, 'patient_id', 'error', 'PATIENT_LINK', '患者关联不存在或父表主键不唯一。', True)

    enc['age'] = pd.to_numeric(enc['age'], errors='coerce')
    for i in enc.index[enc['age'].isna() | ~enc['age'].between(0, 120)]:
        issue('encounters', i, 'age', 'error', 'AGE_INVALID', '年龄缺失、非数值或超出0—120岁的数据检查范围。', True)

    for table, cols in [('encounters', ['admission_date', 'discharge_date', 'surgery_date']), ('labs', ['sample_time'])]:
        f = tables[table]
        for col in cols:
            values = []
            f['_' + col + '_has_time'] = f[col].map(lambda v: bool(re.search(r'[ T]\d{1,2}:\d{2}', string(v))))
            for i, v in f[col].items():
                if pd.isna(v):
                    parsed = pd.NaT
                elif DATE_PATTERN.fullmatch(string(v)):
                    parsed = pd.to_datetime(v, errors='coerce', format='mixed')
                else:
                    parsed = pd.NaT
                required = col in ['admission_date', 'sample_time']
                if pd.isna(parsed) and (pd.notna(v) or required):
                    issue(table, i, col, 'error', 'DATE_INVALID', '日期缺失或不符合年-月-日格式。', True)
                elif pd.notna(parsed) and col in ['admission_date', 'sample_time'] and not f.at[i, '_' + col + '_has_time']:
                    issue(table, i, col, 'warning', 'DATE_ONLY', '来源仅有日期，不能推定准确时刻；不用于小时级CRP基线选择。')
                values.append(parsed)
            f[col] = pd.to_datetime(values)
    for i in enc.index[enc['discharge_date'].notna() & enc['admission_date'].notna() & (enc['discharge_date'] < enc['admission_date'])]:
        issue('encounters', i, 'discharge_date', 'error', 'DATE_ORDER', '出院早于入院，排除该住院事件。', True)
    for i in enc.index[enc['surgery_date'].notna() & ((enc['surgery_date'] < enc['admission_date']) | (enc['discharge_date'].notna() & (enc['surgery_date'] > enc['discharge_date'])))]:
        issue('encounters', i, 'surgery_date', 'error', 'SURGERY_TIME', '手术时间不在已记录的住院时间范围内。', True)
    for i in enc.index[~enc['diagnosis'].isin(DIAGNOSES)]:
        issue('encounters', i, 'diagnosis', 'warning', 'DIAGNOSIS_UNKNOWN', '诊断缺失或未映射；保留来源标签，不自动确诊或归类。')
    for i in enc.index[~enc['procedure'].isin(PROCEDURES)]:
        issue('encounters', i, 'procedure', 'warning', 'PROCEDURE_UNKNOWN', '手术方式缺失或不在字典，保留为未知。')
    enc['diagnosis'] = enc['diagnosis'].fillna('UNKNOWN')
    enc['procedure'] = enc['procedure'].where(enc['procedure'].isin(PROCEDURES), 'UNKNOWN')
    unique_patients = patients.loc[patients['_eligible'], ['patient_id', 'sex']]
    valid_enc = enc.loc[enc['_eligible']].merge(unique_patients, on='patient_id', how='left', validate='many_to_one')
    valid_enc['length_of_stay_days'] = (valid_enc['discharge_date'] - valid_enc['admission_date']).dt.total_seconds() / 86400
    enc_lookup = valid_enc.set_index('encounter_id')

    analyte_alias = {'CRP': 'CRP', 'C反应蛋白': 'CRP', 'C-反应蛋白': 'CRP', '全血C-反应蛋白': 'WBCRP', '常规CRP': 'CRP', 'HSCRP': 'HSCRP', 'hsCRP': 'HSCRP', '超敏CRP': 'HSCRP', '超敏C反应蛋白': 'HSCRP', 'WBC': 'WBC', '白细胞计数': 'WBC', '白细胞': 'WBC', 'ESR': 'ESR', '血沉': 'ESR', '动态血沉': 'ESR'}
    specimen_alias = {'血清': 'serum', 'serum': 'serum', '全血': 'whole_blood', 'whole_blood': 'whole_blood', '血浆': 'plasma', 'plasma': 'plasma', '脑脊液': 'csf', 'csf': 'csf'}
    units = {'CRP': {'mg/L': (1, 'mg/L'), 'mg/dL': (10, 'mg/L')}, 'HSCRP': {'mg/L': (1, 'mg/L'), 'mg/dL': (10, 'mg/L')},
             'WBCRP': {'mg/L': (1, 'mg/L'), 'mg/dL': (10, 'mg/L')}, 'WBC': {'10^9/L': (1, '10^9/L'), '10^3/uL': (1, '10^9/L')}, 'ESR': {'mm/h': (1, 'mm/h')}}
    labs['analyte'] = labs['analyte'].map(lambda v: analyte_alias.get(string(v), string(v)))
    labs['specimen'] = labs['specimen'].map(lambda v: specimen_alias.get(string(v), string(v)))
    numeric, comparators, normalized_units = [], [], []
    for i, row in labs.iterrows():
        match = re.fullmatch(r'\s*(<=|>=|<|>)?\s*([+-]?\d+(?:\.\d+)?)\s*', string(row['value']))
        value = float(match[2]) if match else float('nan')
        comparator = (match[1] or '=') if match else ''
        if row['analyte'] in units and (not match or value < 0):
            issue('labs', i, 'value', 'error', 'LAB_VALUE', '已配置数值项目的结果缺失、无法解析或为负数，排除该结果。', True)
        elif not match:
            issue('labs', i, 'value', 'warning', 'TEXT_RESULT', '保留文本/缺失结果，不作为准确数值统计。')
        elif comparator != '=':
            issue('labs', i, 'value', 'warning', 'CENSORED_VALUE', '检测界限值不是准确测量，不参与准确值描述统计。')
        conversion = units.get(row['analyte'], {}).get(string(row['unit']))
        if conversion:
            value *= conversion[0]
            unit = conversion[1]
        else:
            known = row['analyte'] in units
            issue('labs', i, 'unit', 'error' if known else 'warning', 'UNIT_UNSUPPORTED' if known else 'UNIT_UNMAPPED',
                  '已配置项目的单位不支持，排除该结果。' if known else '保留原项目与单位，未作换算或临床判读。', known)
            unit = string(row['unit'])
        numeric.append(value); comparators.append(comparator); normalized_units.append(unit)
        if row['encounter_id'] not in enc_lookup.index:
            issue('labs', i, 'encounter_id', 'error', 'ENCOUNTER_LINK', '住院关联不存在或对应住院未通过质量检查。', True)
        elif pd.notna(row['sample_time']):
            episode = enc_lookup.loc[row['encounter_id']]
            if row['sample_time'] < episode['admission_date'] or (pd.notna(episode['discharge_date']) and row['sample_time'] > episode['discharge_date']):
                issue('labs', i, 'sample_time', 'warning', 'OUTSIDE_ENCOUNTER', '采样不在已记录的住院范围内，不纳入本次统计。', True)
        if string(row['specimen']) not in ['serum', 'whole_blood', 'plasma', 'csf']:
            issue('labs', i, 'specimen', 'warning', 'SPECIMEN_UNKNOWN', '标本不明确，保留来源，不能自动当作血清。')
    labs['numeric_value'] = numeric
    labs['comparator'] = comparators
    labs['normalized_unit'] = normalized_units
    labs['source_result_ids'] = labs['result_id']
    usable = labs.loc[labs['_eligible']]
    keys = ['encounter_id', 'analyte', 'specimen', 'sample_time', 'normalized_unit']
    for _, group in usable.groupby(keys, dropna=False, sort=False):
        if len(group) < 2:
            continue
        signatures = group[['numeric_value', 'comparator']].copy()
        signatures['text_result'] = group['value'].where(group['numeric_value'].isna(), '')
        signatures = signatures.drop_duplicates()
        if len(signatures) > 1:
            for i in group.index:
                issue('labs', i, 'value', 'error', 'MEASUREMENT_CONFLICT', '同项目、标本、单位、时间存在冲突结果，整组排除。', True)
        else:
            first = group.index[0]
            labs.at[first, 'source_result_ids'] = '|'.join(group['result_id'].astype(str))
            for i in group.index[1:]:
                issue('labs', i, 'value', 'warning', 'MEASUREMENT_REPEAT', '相同测量重复记录，描述统计合并，保留来源结果编号。', True)
    clean_labs = labs.loc[labs['_eligible']].copy()
    issue_frame = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
    audit.append({'step': 'quality_gate', 'input_encounters': len(enc), 'usable_encounters': len(valid_enc),
                  'input_labs': len(labs), 'usable_labs': len(clean_labs), 'issue_items': len(issues)})
    return Prepared(bundle, tables, issue_frame, valid_enc, clean_labs, audit)


@dataclass(frozen=True)
class CohortSpec:
    age_min: int = 18
    age_max: int = 100
    diagnoses: tuple[str, ...] = ()
    procedures: tuple[str, ...] = ()
    start_date: str | None = None
    end_date: str | None = None
    first_per_patient: bool = True
    baseline_hours: int = 72


def build_cohort(prepared: Prepared, spec: CohortSpec) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0 <= spec.age_min <= spec.age_max <= 120:
        raise ValueError('年龄范围应在0—120岁且下限不大于上限。')
    if spec.baseline_hours <= 0 or spec.baseline_hours > 720:
        raise ValueError('基线窗口应为1—720小时。')
    if spec.start_date and spec.end_date and pd.Timestamp(spec.start_date) > pd.Timestamp(spec.end_date):
        raise ValueError('起始日期不能晚于结束日期。')
    frame = prepared.usable_encounters.copy()
    flow = [{'step': '原始住院行', 'before': len(prepared.tables['encounters']), 'after': len(prepared.tables['encounters']), 'excluded': 0},
            {'step': '通过质量检查', 'before': len(prepared.tables['encounters']), 'after': len(frame), 'excluded': len(prepared.tables['encounters']) - len(frame)}]
    def apply(label, mask):
        nonlocal frame
        before = len(frame); frame = frame.loc[mask].copy()
        flow.append({'step': label, 'before': before, 'after': len(frame), 'excluded': before - len(frame)})
    apply('年龄范围', frame['age'].between(spec.age_min, spec.age_max))
    if spec.diagnoses:
        apply('诊断条件', frame['diagnosis'].isin(spec.diagnoses))
    if spec.procedures:
        apply('手术方式', frame['procedure'].isin(spec.procedures))
    if spec.start_date:
        apply('入院起始日期', frame['admission_date'] >= pd.Timestamp(spec.start_date))
    if spec.end_date:
        apply('入院结束日期', frame['admission_date'] < pd.Timestamp(spec.end_date) + pd.Timedelta(days=1))
    frame = frame.sort_values(['admission_date', 'encounter_id'], kind='stable')
    if spec.first_per_patient:
        apply('筛选后每人最早一次住院', ~frame['patient_id'].duplicated(keep='first'))
    labs = prepared.usable_labs
    candidates = labs.loc[labs['analyte'].eq('CRP') & labs['specimen'].eq('serum') & labs['normalized_unit'].eq('mg/L') & labs['comparator'].eq('=') & labs['encounter_id'].isin(frame['encounter_id'])].copy()
    precision = frame.set_index('encounter_id')['_admission_date_has_time']
    candidates = candidates.loc[candidates['_sample_time_has_time'] & candidates['encounter_id'].map(precision).fillna(False)].copy()
    starts = frame.set_index('encounter_id')['admission_date']
    candidates['_hours'] = (candidates['sample_time'] - candidates['encounter_id'].map(starts)).dt.total_seconds() / 3600
    candidates = candidates.loc[candidates['_hours'].between(0, spec.baseline_hours)].sort_values(['sample_time', 'result_id'], kind='stable')
    first = candidates.drop_duplicates('encounter_id').set_index('encounter_id')
    frame['crp_first_mg_L'] = frame['encounter_id'].map(first['numeric_value'])
    frame['crp_sample_time'] = frame['encounter_id'].map(first['sample_time'])
    frame['crp_source_result_ids'] = frame['encounter_id'].map(first['source_result_ids'])
    return frame.reset_index(drop=True), pd.DataFrame(flow)


def descriptive_tables(cohort: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    total = len(cohort)
    rows = []
    for column, label, unit in [('age', '年龄', '岁'), ('length_of_stay_days', '住院时长', '天'), ('crp_first_mg_L', '窗口内首份准确血清CRP', 'mg/L')]:
        values = pd.to_numeric(cohort[column], errors='coerce').dropna()
        if len(values):
            q1, med, q3 = values.quantile([.25, .5, .75])
            display = f'{med:.2f}（{q1:.2f}—{q3:.2f}）'
        else:
            display = '无可用值'
        rows.append({'指标': label, '单位': unit, '可用n': len(values), '缺失n': total - len(values), '中位数（四分位数）': display})
    missing = pd.DataFrame([{'字段': col, '缺失n': int(cohort[col].isna().sum()), '总n': total,
                             '缺失率%': round(100 * cohort[col].isna().sum() / total, 1) if total else 0}
                            for col in ['age', 'sex', 'discharge_date', 'crp_first_mg_L']])
    # An explicit unknown category is missing information, not a negative/normal finding.
    if total:
        missing.loc[missing['字段'].eq('sex'), '缺失n'] = int(cohort['sex'].eq('U').sum())
        missing.loc[missing['字段'].eq('sex'), '缺失率%'] = round(100 * cohort['sex'].eq('U').sum() / total, 1)
    return pd.DataFrame(rows), missing


def audit_manifest(prepared: Prepared, spec: CohortSpec, cohort: pd.DataFrame, flow: pd.DataFrame):
    return {'app_version': __version__, 'synthetic': prepared.bundle.synthetic, 'source_hashes': prepared.bundle.source_hashes,
            'parameters': asdict(spec), 'statistics_grain': 'one_encounter_per_selected_patient' if spec.first_per_patient else 'encounter',
            'patients': int(cohort['patient_id'].nunique()), 'encounters': len(cohort), 'flow': flow.to_dict('records'),
            'pipeline_steps': prepared.audit, 'source_warnings': prepared.bundle.source_warnings, 'baseline_rule': 'first exact serum CRP in configured post-admission window, within recorded stay; timestamp precision required; HSCRP/plasma/CSF/censored excluded',
            'imputation': 'none', 'inference': 'descriptive only'}
