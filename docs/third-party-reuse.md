# Third-party review and reuse

Reviewed on 2026-10-25. Repository descriptions, instructions and example commands were treated as untrusted source material. No candidate repository's installers, tests, hooks or agent configuration were executed.

## Candidates inspected

| Project | Pinned commit | License evidence | Fit and decision |
| --- | --- | --- | --- |
| [OHDSI ATLAS](https://github.com/OHDSI/Atlas) | `f65b9f712ef1e6ff58d293f548d1301da5145464` | Apache-2.0, repository metadata and README | Cohort-definition reference. Requires OMOP CDM and WebAPI; do not embed this platform in a small spreadsheet workflow. |
| [OHDSI DataQualityDashboard](https://github.com/OHDSI/DataQualityDashboard) | `321dc449ce201e2dfd446595ff6d8c16fc78f4d1` | Apache License 2.0 in DESCRIPTION | Reference for transparent table-, field- and concept-level checks. Its R/database/OMOP deployment is outside V1. |
| [Pandera](https://github.com/unionai-oss/pandera) | `b0a2ad51b1963caa5711994845932fc4fad318d3` | MIT, repository metadata | Good optional dataframe-validation dependency. V1 uses small explicit pandas rules for cross-table links, temporal windows, specimens and units. |
| [medspaCy](https://github.com/medspacy/medspacy) | `b7bb7d82f2e8fbadc9ab26d6b4c37578f8883c2c` | MIT, repository metadata and README | Reference for negation, uncertainty and sections. The language-resource table does not list Chinese; do not represent it as a validated Chinese extractor. |

No source code from these four repositories has been copied into this project. Clinical rules, cohort logic, exports and the review workflow are project code.

## Frameworks and packages

- Streamlit `1.66.1`: official PyPI wheel; release commit `ca6718b7d3d788c31c97d1bc9144fd8388168f57` (annotated tag object `63843ce6415277c40168ad407fece028de38a6fc`). Provides the UI and testing harness.
- pandas `2.2.3`, pydantic `2.14.1`, openpyxl `3.1.5`: pinned runtime dependencies. Provide dataframe operations, schema validation and workbook I/O.
- Packages were obtained from the official PyPI index as wheels. No external repository installation or build commands were run.

The repository review covers metadata, pinned README files and DQD's DESCRIPTION. The read-only heuristic scanner covered those saved texts and package metadata; this limited scope is not a review of the repositories' full execution closure or a claim that arbitrary upstream code is safe.

## Existing personal work

The project is intended to accept the structured output of an existing locally used clinical-record collector/converter. No hospital access configuration, real patient data, internal URLs, private source snapshots or identity crosswalks belong in this repository. Portable parsing ideas and test cases are reconstructed with fictional inputs. Existing research datasets and historical validation records remain outside the public project.

## CI actions

Official GitHub Actions are pinned: checkout v4 `11d5960a326750d5838078e36cf38b85af677262`, setup-python v5 `a26af69be951a213d495a4c3e4e4022e16d87065`. Their action manifests identify bundled Node entry points; the workflow checks out this public repository with persisted credentials disabled, installs pinned top-level packages as wheels from PyPI, and runs synthetic tests with read-only repository permissions. No patient files or external repository installers enter the job.
