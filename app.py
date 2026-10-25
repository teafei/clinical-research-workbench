"""Local-first clinical research preparation workbench. Run with Streamlit."""
from __future__ import annotations
import json
import os
from datetime import date

import pandas as pd
import streamlit as st

from crw import __version__
from crw.data import DIAGNOSES, PROCEDURES, SCHEMA, make_demo, read_csv_files, read_workbook
from crw.pipeline import CohortSpec, prepare, build_cohort, descriptive_tables, audit_manifest
from crw.export import csv_bytes, workbook_bytes, export_package
from crw.extraction import (NOTES, FIELD_LABELS, demo_extraction, ollama_extract,
                            record_review, text_hash)

st.set_page_config(page_title='临床科研工作台', page_icon='◈', layout='wide')
PUBLIC_DEMO = os.environ.get('CRW_PUBLIC_DEMO', '0') == '1'
PAGES = ['工作台总览', '导入与标准化', '数据质控', '队列与统计', '病历结构化', '导出与审计']
st.markdown('''<style>
.stApp {background:#f5f7fb;}
.block-container {padding-top:2.4rem;padding-bottom:3rem;max-width:1350px;}
[data-testid="stSidebar"] {background:#102b46;}
[data-testid="stSidebar"] * {color:#edf4fb;}
[data-testid="stSidebar"] [data-baseweb="radio"] {margin-bottom:.4rem;}
[data-testid="stMetric"] {background:white;padding:18px 22px;border:1px solid #e2e8f0;border-radius:12px;}
[data-testid="stMetricLabel"] {color:#52677e;}
h1,h2,h3 {letter-spacing:-.02em;color:#12324f;}
.eyebrow {color:#168582;font-size:.8rem;letter-spacing:.14em;font-weight:700;}
.hero {background:linear-gradient(115deg,#102f4d,#15585e);padding:28px 34px;border-radius:16px;margin-bottom:24px;}
.hero h1 {color:white;font-size:2rem;margin:5px 0 9px;}
.hero p {color:#d2e4ed;margin:0;font-size:1.02rem;}
.hero .eyebrow {color:#86dad1;}
.step {background:white;border:1px solid #e0e8ef;border-top:3px solid #21938b;border-radius:9px;padding:17px;min-height:130px;}
.step b {color:#153753;}.step p {color:#64778b;font-size:.9rem;margin-top:10px;}
</style>''', unsafe_allow_html=True)


def activate(bundle):
    st.session_state['bundle'] = bundle
    st.session_state['prepared'] = prepare(bundle)
    st.session_state['spec'] = CohortSpec()
    for key in list(st.session_state):
        if key.startswith(('filter_', 'review_', 'extract_', 'download_')):
            del st.session_state[key]


if 'bundle' not in st.session_state:
    activate(make_demo())
bundle = st.session_state['bundle']
prepared = st.session_state['prepared']
spec = st.session_state['spec']
cohort, flow = build_cohort(prepared, spec)

with st.sidebar:
    st.markdown('### ◈ CRW')
    st.caption('CLINICAL RESEARCH\n\nWORKBENCH')
    st.divider()
    page = st.radio('研究流程', PAGES, label_visibility='collapsed', key='navigation')
    st.divider()
    st.caption('当前数据')
    st.write('● 完全合成演示' if bundle.synthetic else '● 本地导入 · 待临床核验')
    st.caption(f'版本 {__version__} · 数据留在当前会话')
    if st.button('重置为合成演示', width='stretch'):
        activate(make_demo())
        st.rerun()


def metrics():
    cols = st.columns(4)
    cols[0].metric('原始患者行', f'{len(bundle.tables["patients"]):,}')
    cols[1].metric('原始住院行', f'{len(bundle.tables["encounters"]):,}')
    cols[2].metric('当前队列住院', f'{len(cohort):,}')
    cols[3].metric('当前队列患者', f'{cohort.patient_id.nunique():,}')


def table(frame, **kwargs):
    st.dataframe(frame, hide_index=True, width='stretch', **kwargs)


if page == '工作台总览':
    st.markdown('''<div class="hero"><div class="eyebrow">CLINICAL RESEARCH WORKBENCH</div>
    <h1>临床科研工作台</h1>
    <p>整理住院记录，核对检验数据，准备研究队列。</p></div>''', unsafe_allow_html=True)
    metrics()
    st.caption('演示数据从零生成，刻意加入重复、缺失、单位与时间问题。患者数、住院数和问题条目分别统计。' if bundle.synthetic else '当前结果基于来源记录与设定规则，最终研究纳入仍需临床审核。')
    st.subheader('数据整理流程')
    cards = [('01 / 导入', '三表数据契约、中文工作簿适配、输入文件指纹'),
             ('02 / 质控', '主外键、日期、单位、重复与冲突逐项定位'),
             ('03 / 队列', '可调整筛选条件、患者层口径、CRP时间窗'),
             ('04 / 审核与导出', '原文证据、人工确认、参数及处理记录')]
    for col, (title, body) in zip(st.columns(4), cards):
        with col:
            st.markdown(f'<div class="step"><b>{title}</b><p>{body}</p></div>', unsafe_allow_html=True)
    left, right = st.columns([1.25, 1])
    with left:
        st.subheader('队列筛选概览')
        table(flow)
    with right:
        st.subheader('待处理的数据问题')
        if prepared.issues.empty:
            st.success('当前规则未发现问题。')
        else:
            summary = prepared.issues.groupby('severity', sort=False).size().rename('问题条目')
            st.bar_chart(summary, color='#168582', height=220)
        st.caption('一条记录可有多个问题；警告不一定排除记录，错误与关联冲突按规则阻断。')
    st.info('病历结构化提供“预置候选演示”和“本地模型”两种入口。所有候选需逐字段人工审核；预置演示不代表模型推理或准确率。')

elif page == '导入与标准化':
    st.title('导入与标准化')
    st.write('接受标准三表 CSV / Excel，或已有采集整理程序的中文工作簿。原始文件与标准化结果分别保留。')
    if PUBLIC_DEMO:
        st.info('公开演示仅使用内置合成数据，文件上传已关闭。真实资料请使用本地版本。')
    else:
        mode = st.radio('文件格式', ['Excel 工作簿', '三个 CSV 文件'], horizontal=True)
        with st.form('import_form'):
            excel = st.file_uploader('Excel：标准三表或“病例总表 / 检验项目明细”', type=['xlsx']) if mode == 'Excel 工作簿' else None
            csvs = {}
            if mode == '三个 CSV 文件':
                for name in SCHEMA:
                    csvs[name] = st.file_uploader(name + '.csv', type=['csv'], key='upload_' + name)
            submitted = st.form_submit_button('验证并导入', type='primary')
        if submitted:
            try:
                if mode == 'Excel 工作簿':
                    if excel is None:
                        raise ValueError('请先选择工作簿。')
                    new_bundle = read_workbook(excel.getvalue())
                else:
                    if any(f is None for f in csvs.values()):
                        raise ValueError('请提供全部三个 CSV 文件。')
                    new_bundle = read_csv_files({k: f.getvalue() for k, f in csvs.items()})
                activate(new_bundle)
                st.session_state['import_success'] = True
                st.rerun()
            except (ValueError, TypeError) as exc:
                st.error(str(exc))
        if st.session_state.pop('import_success', False):
            st.success('导入完成。输入文件未改写，规则检查已生成。')
        st.caption('单个文件≤10 MB；每表≤100,000行、Excel≤100列。工具不读取HIS、不自动联网传输文件。')
    choice = st.selectbox('查看数据表', list(SCHEMA))
    raw_tab, normalized_tab = st.tabs(['原始导入字段', '标准化结果'])
    with raw_tab:
        table(bundle.tables[choice].head(300))
    with normalized_tab:
        table(prepared.tables[choice].head(300))
    st.caption('界面最多显示前300行；完整标准化结果可在导出页面取得。_source_row 为源表行号。')
    with st.expander('数据契约与模板'):
        for name, columns in SCHEMA.items():
            st.write(f'**{name}**：' + ' / '.join(columns))
        st.write('标识字段按文本读取；缺失不会自动插补。既有中文适配器保留待核定诊断、来源质量标记和报告定位字段，不根据姓名合并患者。')
        st.download_button('下载标准三表演示工作簿', workbook_bytes(make_demo().tables), 'synthetic_import_template.xlsx')

elif page == '数据质控':
    st.title('数据质控')
    st.write('每个问题关联来源表、行号、记录键与检查规则。重复主键和冲突测量整组排除，保留原始输入供核查。')
    c1, c2, c3 = st.columns(3)
    c1.metric('问题条目', len(prepared.issues))
    c2.metric('可用住院行', len(prepared.usable_encounters))
    c3.metric('可用检验行', len(prepared.usable_labs))
    if bundle.source_warnings:
        st.warning('上游数据仍有待核实标记；结构关联成功不代表患者身份与研究资格已确认。')
        table(pd.DataFrame(bundle.source_warnings))
    issues = prepared.issues
    severity = st.multiselect('问题级别', ['error', 'warning'], default=['error', 'warning'])
    codes = st.multiselect('检查规则（留空查看全部）', sorted(issues.code.unique()))
    shown = issues.loc[issues.severity.isin(severity)]
    if codes:
        shown = shown.loc[shown.code.isin(codes)]
    table(shown.head(500))
    st.download_button('下载完整质量问题清单', csv_bytes(issues), 'quality_issues.csv', 'text/csv')
    with st.expander('关键规则'):
        st.write('主键唯一性、患者—住院—检验外键、年龄范围、入出院顺序、手术与采样时间、已配置单位、相同测量冲突。')
        st.write('CRP、全血CRP与超敏CRP分别保存；血清、血浆、全血、脑脊液不混合。<5这类检测界限保留比较符号，不能当作准确数值。')
        st.write('未配置项目保留原文，不自动给出临床判读。未知、未查和未记载不等于阴性。')

elif page == '队列与统计':
    st.title('队列与描述统计')
    st.write('筛选可回溯，统计口径明确。先执行纳排条件，再按需选择每名患者最早的一次符合条件住院。')
    with st.form('cohort_form'):
        left, right = st.columns(2)
        with left:
            ages = st.slider('年龄范围', 0, 120, (spec.age_min, spec.age_max), key='filter_age')
            diagnoses = st.multiselect('诊断（留空=全部）', sorted(prepared.usable_encounters.diagnosis.unique()), default=list(spec.diagnoses),
                                      format_func=lambda v: DIAGNOSES.get(v, str(v)), key='filter_diagnosis')
            procedures = st.multiselect('手术方式（留空=全部）', sorted(prepared.usable_encounters.procedure.unique()), default=list(spec.procedures),
                                       format_func=lambda v: PROCEDURES.get(v, str(v)), key='filter_procedure')
        with right:
            first = st.checkbox('每名患者保留筛选后最早一次住院', value=spec.first_per_patient, key='filter_first')
            hours = st.number_input('入院后基线CRP窗口（小时）', 1, 720, spec.baseline_hours, key='filter_hours')
            use_dates = st.checkbox('限制入院日期', value=bool(spec.start_date), key='filter_use_dates')
            dates = st.date_input('入院日期起止', value=(date.fromisoformat(spec.start_date) if spec.start_date else date(2025, 1, 1),
                                                       date.fromisoformat(spec.end_date) if spec.end_date else date(2026, 12, 31)), key='filter_dates')
        apply_filters = st.form_submit_button('更新队列', type='primary')
    if apply_filters:
        try:
            if use_dates and len(dates) != 2:
                raise ValueError('请选择完整的起止日期。')
            new_spec = CohortSpec(ages[0], ages[1], tuple(diagnoses), tuple(procedures),
                                  dates[0].isoformat() if use_dates else None, dates[1].isoformat() if use_dates else None,
                                  first, int(hours))
            build_cohort(prepared, new_spec)
            st.session_state['spec'] = new_spec
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    metrics()
    st.caption(f'当前口径：{"每位患者一条符合条件住院" if spec.first_per_patient else "住院事件（同人可重复）"}；CRP窗口0—{spec.baseline_hours}小时，仅首份准确血清值。')
    baseline, missingness = descriptive_tables(cohort)
    a, b, c = st.tabs(['筛选流程与描述', '缺失与分布', '队列明细'])
    with a:
        table(flow)
        table(baseline)
    with b:
        table(missingness)
        if len(cohort):
            st.bar_chart(cohort.diagnosis.map(lambda v: DIAGNOSES.get(v, str(v))).value_counts(), color='#168582', height=260)
        else:
            st.info('当前条件无符合记录，可调整筛选条件。')
    with c:
        table(cohort.head(500))

elif page == '病历结构化':
    st.title('病历结构化 · 证据与人工审核')
    st.write('原文 → 结构化候选 → 证据校验 → 逐字段人工确认。未确认候选不会进入审核通过结果。')
    mode = st.radio('候选生成方式', ['预置候选演示', '本地 Ollama 模型'], horizontal=True, key='extract_mode')
    if mode == '预置候选演示':
        st.info('以下候选为预先编写的演示内容，用于展示审核流程；不调用模型，不构成准确率评测。')
        note_id = st.selectbox('合成病例', list(NOTES), key='extract_note')
        source = st.text_area('合成病历原文', NOTES[note_id], height=120, disabled=True, key='extract_source_' + note_id)
        model_name, endpoint = '', ''
    else:
        st.info('仅连接本机已安装的 Ollama 模型。工具不下载模型、不连接云端API；当前版本尚无真实模型质量评测。')
        source = st.text_area('待结构化原文（请先去除直接身份信息）', height=160, max_chars=12000, key='extract_local_source', disabled=PUBLIC_DEMO)
        x, y = st.columns(2)
        model_name = x.text_input('本机已安装模型名', key='extract_model', disabled=PUBLIC_DEMO)
        endpoint = y.text_input('本机服务地址', 'http://127.0.0.1:11434', key='extract_endpoint', disabled=PUBLIC_DEMO)
        if PUBLIC_DEMO:
            st.warning('公开演示已关闭自定义病历与本地模型连接。')
    signature = text_hash(mode + source + model_name + endpoint)
    if st.session_state.get('extract_signature') != signature:
        st.session_state['extract_candidates'] = []
        st.session_state['review_log'] = []
        st.session_state['extract_signature'] = signature
    if st.button('生成待审核候选', type='primary', disabled=PUBLIC_DEMO and mode != '预置候选演示'):
        try:
            with st.spinner('正在生成与校验候选…'):
                result = demo_extraction(note_id, source) if mode == '预置候选演示' else ollama_extract(source, model_name, endpoint)
            st.session_state['extract_candidates'] = result
            st.session_state['review_log'] = []
            st.session_state['extract_engine'] = 'preset_demo_not_model' if mode == '预置候选演示' else 'ollama:' + model_name
        except Exception as exc:
            st.error('候选生成失败：' + str(exc)[:300])
    candidates = st.session_state.get('extract_candidates', [])
    if candidates:
        st.subheader('逐字段审核')
        reviewer = st.text_input('审核者标识（必填）', key='review_name', placeholder='例如 reviewer-01')
        statuses = {'present': '明确有', 'absent': '明确无 / 阴性', 'unknown': '未知 / 未查', 'planned': '计划，未实施'}
        for idx, candidate in enumerate(candidates):
            with st.container(border=True):
                left, right = st.columns([2.5, 1])
                with left:
                    st.markdown(f'**{FIELD_LABELS[candidate["field"]]}**　·　{statuses[candidate["status"]]}')
                    st.write('候选值：' + str(candidate['value'] or '—'))
                    st.caption('原文证据（字符位置 ' + str(candidate['source_start']) + '—' + str(candidate['source_end']) + '）')
                    st.code(candidate['evidence'] or '无明确原文证据', language=None)
                with right:
                    current = next((r for r in reversed(st.session_state.get('review_log', [])) if r['field'] == candidate['field']), None)
                    st.caption('审核状态：' + (current['review_status'] if current else 'pending'))
                    note = st.text_input('审核备注', key=f'review_note_{signature}_{idx}')
                    yes, no = st.columns(2)
                    accepted = yes.button('通过', key=f'review_yes_{idx}')
                    rejected = no.button('驳回', key=f'review_no_{idx}')
                    if accepted or rejected:
                        try:
                            event = record_review(candidate, source, 'accepted' if accepted else 'rejected', reviewer, note)
                            st.session_state['review_log'].append(event)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
        latest = {r['field']: r for r in st.session_state.get('review_log', [])}
        accepted_rows = [r for r in latest.values() if r['review_status'] == 'accepted']
        st.success(f'已审核通过 {len(accepted_rows)} / {len(candidates)} 个字段。')
        payload = {'engine': st.session_state['extract_engine'], 'source_hash': text_hash(source),
                   'accepted_fields': accepted_rows, 'review_history': st.session_state.get('review_log', [])}
        st.download_button('导出人工审核结果 JSON', json.dumps(payload, ensure_ascii=False, indent=2).encode(), 'reviewed_extraction.json', 'application/json')
        st.caption('证据存在性检查只能确认文本出处，不能证明语义判断正确。审核结论与操作历史均需保留。')

elif page == '导出与审计':
    st.title('导出与审计')
    st.write('将当前队列、质量问题、规则参数和文件指纹一起导出，便于复核与复现。')
    metrics()
    manifest = audit_manifest(prepared, spec, cohort, flow)
    st.subheader('本次分析参数')
    st.json(manifest, expanded=False)
    st.download_button('下载研究准备包 ZIP', export_package(prepared, spec, cohort, flow), 'clinical_research_package.zip', 'application/zip', type='primary')
    st.download_button('仅下载审计记录 JSON', json.dumps(manifest, ensure_ascii=False, indent=2).encode(), 'audit.json', 'application/json')
    st.caption('准备包包括CSV、Excel、队列筛选流程、缺失概览与审计JSON。导出包含临床资料时仍需按本单位要求保存。')
    st.subheader('复核依据')
    st.write('输入文件SHA-256、标准化步骤、可用行数、逐项质量问题、队列条件、患者/住院口径及CRP规则全部写入准备包。')
    st.write('程序不改写输入文件，不进行缺失插补或疗效推断；人工审核病历结果单独导出，避免混入尚未确认的候选。')
