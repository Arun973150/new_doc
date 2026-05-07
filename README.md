# COBOL Migration Documentation Hub

This repository contains a COBOL documentation and migration-analysis workspace built around the AWS CardDemo mainframe sample. The project parses COBOL programs, copybooks, BMS screens, and JCL; stores the extracted facts in SQLite; generates cross-linked Markdown documentation; and provides a Streamlit dashboard for exploring the system.

## Main Folders

| Path | Purpose |
| --- | --- |
| `doc_demo/` | Main documentation pipeline, dashboard, parsers, generated docs, and SQLite knowledge base |
| `doc_demo/carddemo/` | Local CardDemo source copy used by the pipeline |
| `doc_demo/docs/` | Generated Markdown documentation for programs, modules, screens, JCL, business rules, diagrams, and data dictionary |
| `doc_demo/src/` | Python source for parsing, loading, generation, validation, Streamlit UI, and artifact documentation agents |
| `aws-mainframe-modernization-carddemo/` | Additional CardDemo source copy |
| `data/` | Top-level data assets |

## Quick Start

Run the dashboard:

```powershell
cd doc_demo
streamlit run src/app.py
```

Regenerate the knowledge base and documentation:

```powershell
cd doc_demo
python run_pipeline.py
```

## Documentation

Start here:

- Full project guide: [`doc_demo/README.md`](doc_demo/README.md)
- Generated system overview: [`doc_demo/docs/00-SYSTEM-OVERVIEW.md`](doc_demo/docs/00-SYSTEM-OVERVIEW.md)
- CardDemo source README: [`doc_demo/carddemo/README.md`](doc_demo/carddemo/README.md)
- Standalone JCL/BMS docs: [`doc_demo/docs/standalone-artifacts/`](doc_demo/docs/standalone-artifacts/)

## Current Snapshot

The checked-in documentation snapshot covers 44 COBOL programs, 68 copybooks, 21 BMS screens, 55 JCL jobs, 19 functional modules, and 447 business rules.

