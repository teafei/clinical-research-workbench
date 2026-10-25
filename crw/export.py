"""In-memory, spreadsheet-safe research packages with explicit audit metadata."""
from __future__ import annotations
from io import BytesIO
import json
import zipfile
import pandas as pd
from .pipeline import Prepared, CohortSpec, audit_manifest, descriptive_tables


def spreadsheet_safe(value):
    if isinstance(value, str) and value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def public_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame[[c for c in frame if not str(c).startswith('_')]].copy()
    for col in output:
        if pd.api.types.is_datetime64_any_dtype(output[col]):
            output[col] = output[col].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
            precision = '_' + col + '_has_time'
            if precision in frame:
                only_date = frame[col].notna() & ~frame[precision]
                output.loc[only_date, col] = frame.loc[only_date, col].dt.strftime('%Y-%m-%d')
        else:
            output[col] = output[col].map(spreadsheet_safe)
    return output


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return public_columns(frame).to_csv(index=False).encode('utf-8-sig')


def workbook_bytes(tables: dict[str, pd.DataFrame]) -> bytes:
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        for name, frame in tables.items():
            public_columns(frame).to_excel(writer, sheet_name=name[:31], index=False)
            sheet = writer.sheets[name[:31]]
            sheet.freeze_panes = 'A2'
            sheet.auto_filter.ref = sheet.dimensions
            for col in sheet.columns:
                letter = col[0].column_letter
                sheet.column_dimensions[letter].width = min(50, max(12, max(len(str(c.value or '')) for c in col[:50]) + 2))
    return stream.getvalue()


def export_package(prepared: Prepared, spec: CohortSpec, cohort: pd.DataFrame, flow: pd.DataFrame) -> bytes:
    baseline, missingness = descriptive_tables(cohort)
    tables = {'cohort': cohort, 'quality_issues': prepared.issues, 'cohort_flow': flow, 'baseline': baseline, 'missingness': missingness}
    manifest = audit_manifest(prepared, spec, cohort, flow)
    # Add eligible standardized rows; input files are not rewritten or bundled into the analysis package.
    tables['patients_standard'] = prepared.tables['patients'].loc[prepared.tables['patients']['_eligible']]
    tables['encounters_standard'] = prepared.usable_encounters
    tables['labs_standard'] = prepared.usable_labs
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, frame in tables.items():
            archive.writestr(name + '.csv', csv_bytes(frame))
        archive.writestr('research_tables.xlsx', workbook_bytes(tables))
        archive.writestr('audit.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr('README.txt', '研究准备导出包\n统计以audit.json中的grain和参数为准。未知与未查不代表阴性。无插补或因果推断。\nCRP仅取设定时间窗内的首份准确血清值，排除超敏CRP、脑脊液和检测界限值。\nCSV标识字段在Excel中应按文本导入；工作簿保留文本标识。危险公式前缀按文字转义。\n')
    return stream.getvalue()
