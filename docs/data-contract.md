# Data contract and existing-format adapters

The interface is designed around existing collector/converter outputs and a lightweight patient–encounter index. Public examples are generated from scratch and contain no hospital records.

## Grain

- `patients`: one stable source patient key. Names are not identity keys.
- `encounters`: one source encounter key linked to a patient key. An inpatient number alone is not assumed to identify a person across all admissions.
- `labs`: one source result row linked to one encounter, preserving analyte, original value, comparator, unit, specimen, sampling time and source result IDs.
- Source data-quality warnings remain visible. Successful key matching does not independently verify a patient's clinical identity.

## Existing structured workbook mapping

This mapping describes a known Chinese workbook format. It carries column names only, not private file paths or patient-level values.

| Source sheet | Source field | Target concept |
| --- | --- | --- |
| 病例总表 | 原患者ID | patient_id |
| 病例总表 | 住院关联键 | encounter_id |
| 病例总表 | 年龄（岁） | age at this admission |
| 病例总表 | 入院时间（原试跑表） | admission_date |
| 病例总表 | 出院时间（原试跑表） | discharge_date |
| 病例总表 | 原表诊断（待核定） | source diagnosis label, pending clinical confirmation |
| 检验项目明细 | 检验项目关联键 | result_id |
| 检验项目明细 | 住院关联键 | encounter_id |
| 检验项目明细 | 项目名称 | analyte |
| 检验项目明细 | 结果原文 / 比较符号 / 数值或检测界限 | original result and comparator, never replace a detection limit with an exact value |
| 检验项目明细 | 单位原文 / 标本类型 / 送检时间 | unit / specimen / sample_time |
| 检验项目明细 | 报告关联键 / 源JSON路径 / 源文件 | provenance, retained in the local adapter |
| 质量核对 | 核对代码 / 核对说明 | unresolved source-quality flags |

An optional filled clinical sheet is a separate review layer. A field that contains “未查” or “未知” is not a negative finding. Its row-level evidence is not automatically a clinically adjudicated gold standard.

## Normalization and cohort rules

- Normalize whitespace and supported labels while retaining the raw import separately in memory.
- Convert only explicitly supported analyte–unit pairs. CRP mg/dL × 10 becomes mg/L; hsCRP remains a different analyte.
- Do not infer a year for orders containing month/day only.
- Reject duplicate primary-key groups and broken foreign-key links from analysis; do not silently select a convenient row.
- Preserve planned procedures separately from performed procedures.
- Define baseline lab windows explicitly from admission and stay boundaries. First observed is not automatically an admission endpoint.
- Cohort filters act on recorded source labels; they do not diagnose disease or adjudicate clinical eligibility.
- Count patients and encounters separately. If one admission per patient is requested, report whether selection occurs before or after other cohort filters.
- Never add an outcome, impute a missing field, infer a negative result or fill a clinical timestamp just to make the demo complete.

## Boundary with existing programs

The collector remains an upstream local tool. The workbench accepts its derived output without embedding hospital selectors or connection settings. A SQLite master index can provide a future upstream encounter list; empty lab, operation or imaging tables do not constitute connected data feeds. Platform-specific image-review/Excel-COM exporters are separate adapters, not replacements for the generic data contract.
