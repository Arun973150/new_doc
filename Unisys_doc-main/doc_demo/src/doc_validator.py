"""
Documentation Validator
Runs three validation checks against the generated docs:

  1. Structural — every program has a doc, required sections present, links resolve
  2. Factual    — every program ID / copybook / paragraph / line in docs exists in SQLite
  3. Coverage   — every CALL / COPY / CICS XCTL / JCL EXEC in source appears in the doc

Usage (standalone):
    python -m src.doc_validator --db data/cobol_knowledge.db --docs docs/

Usage (programmatic):
    from doc_validator import validate_docs
    report = validate_docs(db_path, docs_dir)
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

from rich.console import Console
from rich.table import Table

console = Console(force_terminal=True, highlight=False)

REQUIRED_PROGRAM_SECTIONS = [
    "## Business Purpose",
    "## Dependency Context",
    "## Statement Profile",
    "## Control Flow",
    "## Paragraphs",
]


@dataclass
class ValidationReport:
    structural_errors: List[str] = field(default_factory=list)
    structural_warnings: List[str] = field(default_factory=list)
    factual_errors: List[str] = field(default_factory=list)
    coverage_gaps: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not (self.structural_errors or self.factual_errors or self.coverage_gaps)

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "stats": self.stats,
            "structural_errors": self.structural_errors,
            "structural_warnings": self.structural_warnings,
            "factual_errors": self.factual_errors,
            "coverage_gaps": self.coverage_gaps,
        }


# ───────────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────────

def _load_sqlite_facts(db_path: str) -> Dict[str, Set[str]]:
    """Pull ground-truth identifiers from SQLite for the factual check."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    facts: Dict[str, Set[str]] = {
        "programs": set(),
        "copybooks": set(),
        "paragraphs": set(),         # plain paragraph names
        "screens": set(),
        "jcl_jobs": set(),
        "modules": set(),
        "business_rules": set(),
        "data_items": set(),
        "files": set(),
    }

    cur.execute("SELECT program_id FROM programs")
    facts["programs"] = {r["program_id"] for r in cur.fetchall()}

    cur.execute("SELECT copybook_name FROM copybooks")
    facts["copybooks"] = {r["copybook_name"] for r in cur.fetchall()}

    cur.execute("SELECT paragraph_name FROM paragraphs")
    facts["paragraphs"] = {r["paragraph_name"] for r in cur.fetchall()}

    try:
        cur.execute("SELECT screen_name, map_name, mapset_name FROM screens")
        for r in cur.fetchall():
            for v in (r["screen_name"], r["map_name"], r["mapset_name"]):
                if v:
                    facts["screens"].add(v)
    except Exception:
        pass

    try:
        cur.execute("SELECT job_name FROM jcl_jobs")
        facts["jcl_jobs"] = {r["job_name"] for r in cur.fetchall()}
    except Exception:
        pass

    try:
        cur.execute("SELECT DISTINCT step_name FROM jcl_steps")
        for r in cur.fetchall():
            if r["step_name"]:
                facts["jcl_jobs"].add(r["step_name"])
    except Exception:
        pass

    cur.execute("SELECT module_name FROM modules")
    facts["modules"] = {r["module_name"] for r in cur.fetchall()}

    try:
        cur.execute("SELECT rule_id FROM business_rules")
        facts["business_rules"] = {r["rule_id"] for r in cur.fetchall() if r["rule_id"]}
    except Exception:
        pass

    cur.execute("SELECT DISTINCT name FROM data_items")
    facts["data_items"] = {r["name"] for r in cur.fetchall() if r["name"]}

    try:
        cur.execute("SELECT DISTINCT file_name FROM files")
        facts["files"] = {r["file_name"] for r in cur.fetchall() if r["file_name"]}
    except Exception:
        pass

    conn.close()
    return facts


def _load_expected_relations(db_path: str) -> Dict[str, Dict[str, Set[str]]]:
    """For coverage check: what each program SHOULD reference."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    relations: Dict[str, Dict[str, Set[str]]] = {}

    cur.execute("SELECT program_id FROM programs")
    for r in cur.fetchall():
        relations[r["program_id"]] = {
            "calls": set(),
            "copybooks": set(),
            "cics_xctl": set(),
            "jcl_jobs": set(),
        }

    cur.execute("SELECT caller_program, called_program FROM program_calls")
    for r in cur.fetchall():
        if r["caller_program"] in relations and r["called_program"] not in (None, "UNKNOWN"):
            relations[r["caller_program"]]["calls"].add(r["called_program"])

    cur.execute("SELECT program_id, copybook_name FROM copybook_usage")
    for r in cur.fetchall():
        if r["program_id"] in relations:
            relations[r["program_id"]]["copybooks"].add(r["copybook_name"])

    try:
        cur.execute("SELECT program_id, command, details_json FROM exec_cics WHERE command IN ('XCTL','LINK')")
        for r in cur.fetchall():
            if r["program_id"] not in relations:
                continue
            try:
                d = json.loads(r["details_json"] or "{}")
                inner = d.get("details", d) or {}
                target = inner.get("program")
                if target:
                    relations[r["program_id"]]["cics_xctl"].add(target)
            except Exception:
                pass
    except Exception:
        pass

    try:
        cur.execute("SELECT program, job_name FROM jcl_steps WHERE program IS NOT NULL")
        for r in cur.fetchall():
            if r["program"] in relations:
                relations[r["program"]]["jcl_jobs"].add(r["job_name"])
    except Exception:
        pass

    conn.close()
    return relations


# ───────────────────────────────────────────────────────────────────────────────
# Check 1: Structural
# ───────────────────────────────────────────────────────────────────────────────

def _check_structural(facts: Dict[str, Set[str]], docs_dir: Path,
                       report: ValidationReport) -> None:
    programs_dir = docs_dir / "programs"

    # Every program must have a doc file
    missing_docs = []
    for pid in facts["programs"]:
        doc = programs_dir / f"{pid}.md"
        if not doc.exists():
            missing_docs.append(pid)
    if missing_docs:
        report.structural_errors.append(
            f"Missing program docs ({len(missing_docs)}): {', '.join(sorted(missing_docs)[:10])}"
            + ("..." if len(missing_docs) > 10 else "")
        )

    # Required sections present + non-empty
    empty_section_count = 0
    missing_section_count = 0
    for pid in facts["programs"]:
        doc = programs_dir / f"{pid}.md"
        if not doc.exists():
            continue
        content = doc.read_text(encoding="utf-8", errors="ignore")
        for section in REQUIRED_PROGRAM_SECTIONS:
            if section not in content:
                report.structural_warnings.append(f"{pid}: missing section '{section}'")
                missing_section_count += 1
                continue
            # Check the section has at least 30 chars of content after its heading
            idx = content.find(section)
            tail = content[idx + len(section): idx + len(section) + 200]
            if len(tail.strip()) < 30:
                report.structural_warnings.append(f"{pid}: section '{section}' appears empty")
                empty_section_count += 1

    # Internal markdown links resolve
    broken_links = 0
    link_pat = re.compile(r"\]\(([^)]+\.md)(?:#[^)]*)?\)")
    for md_file in docs_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in link_pat.finditer(content):
            link = m.group(1)
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            target = (md_file.parent / link).resolve()
            if not target.exists():
                broken_links += 1
                if broken_links <= 20:  # cap noise
                    report.structural_warnings.append(
                        f"Broken link in {md_file.relative_to(docs_dir)}: -> {link}"
                    )

    report.stats["program_docs_expected"] = len(facts["programs"])
    report.stats["program_docs_missing"] = len(missing_docs)
    report.stats["empty_sections"] = empty_section_count
    report.stats["missing_sections"] = missing_section_count
    report.stats["broken_links"] = broken_links


# ───────────────────────────────────────────────────────────────────────────────
# Check 2: Factual cross-check
# ───────────────────────────────────────────────────────────────────────────────

# Identifier pattern: allow upper/digit + dash, 3-12 chars (typical COBOL names)
ID_PAT = re.compile(r"`([A-Z][A-Z0-9-]{2,11})`")

# Skip these common false positives — keywords that look like identifiers
NOISE = {
    "COBOL", "CICS", "JCL", "BMS", "VSAM", "SQL", "DB2", "ONLINE", "BATCH",
    "MAIN", "ENTRY", "EXIT", "END", "TRUE", "FALSE", "NULL", "UNKNOWN",
    "INPUT", "OUTPUT", "READ", "WRITE", "OPEN", "CLOSE", "CALL", "PERFORM",
    "MOVE", "IF", "ELSE", "EVALUATE", "WHEN", "GOTO", "STOP", "GOBACK",
    "SEND", "RECEIVE", "XCTL", "LINK", "RETURN", "ASKTIME", "SYNCPOINT",
    "STARTBR", "READNEXT", "READPREV", "ENDBR", "REWRITE", "DELETE",
    "WORKING-STORAGE", "LINKAGE", "FILE",
}


def _check_factual(facts: Dict[str, Set[str]], docs_dir: Path,
                    report: ValidationReport) -> None:
    programs_dir = docs_dir / "programs"
    if not programs_dir.exists():
        return

    known_ids = (
        facts["programs"]
        | facts["copybooks"]
        | facts["modules"]
        | facts["jcl_jobs"]
        | facts["screens"]
        | facts["business_rules"]
        | facts["data_items"]
        | facts["paragraphs"]
        | facts["files"]
    )

    unknown_refs: Dict[str, Set[str]] = {}  # doc_file -> set of unknown identifiers

    for doc in programs_dir.glob("*.md"):
        content = doc.read_text(encoding="utf-8", errors="ignore")
        for m in ID_PAT.finditer(content):
            ident = m.group(1)
            if ident in NOISE or ident in known_ids:
                continue
            # Strip trailing dash artifacts and re-test
            cleaned = ident.rstrip("-")
            if cleaned in known_ids or cleaned in NOISE:
                continue
            unknown_refs.setdefault(doc.stem, set()).add(ident)

    bad_count = sum(len(v) for v in unknown_refs.values())
    if bad_count:
        # Report top offenders
        for doc_stem, refs in list(unknown_refs.items())[:15]:
            sample = sorted(refs)[:8]
            report.factual_errors.append(
                f"{doc_stem}.md references unknown identifiers: {', '.join(sample)}"
                + (f" (+{len(refs) - 8} more)" if len(refs) > 8 else "")
            )

    report.stats["unknown_identifier_refs"] = bad_count


# ───────────────────────────────────────────────────────────────────────────────
# Check 3: Coverage
# ───────────────────────────────────────────────────────────────────────────────

def _check_coverage(relations: Dict[str, Dict[str, Set[str]]], docs_dir: Path,
                     report: ValidationReport) -> None:
    programs_dir = docs_dir / "programs"
    if not programs_dir.exists():
        return

    total_expected = 0
    total_missing = 0

    for pid, expected in relations.items():
        doc = programs_dir / f"{pid}.md"
        if not doc.exists():
            continue  # missing doc already flagged in structural check
        content = doc.read_text(encoding="utf-8", errors="ignore")

        # Each expected reference: just check substring presence
        for kind, ids in expected.items():
            for ident in ids:
                total_expected += 1
                if ident not in content:
                    total_missing += 1
                    report.coverage_gaps.append(
                        f"{pid}.md does not reference {kind}: {ident}"
                    )

    report.stats["coverage_expected_refs"] = total_expected
    report.stats["coverage_missing_refs"] = total_missing


# ───────────────────────────────────────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────────────────────────────────────

def validate_docs(db_path: str, docs_dir: str) -> ValidationReport:
    """Run all three validation checks and return a report."""
    report = ValidationReport()
    docs_path = Path(docs_dir)

    if not docs_path.exists():
        report.structural_errors.append(f"Docs directory does not exist: {docs_dir}")
        return report

    facts = _load_sqlite_facts(db_path)
    relations = _load_expected_relations(db_path)

    console.print("[cyan]Running structural check...[/cyan]")
    _check_structural(facts, docs_path, report)

    console.print("[cyan]Running factual cross-check...[/cyan]")
    _check_factual(facts, docs_path, report)

    console.print("[cyan]Running coverage check...[/cyan]")
    _check_coverage(relations, docs_path, report)

    return report


def print_report(report: ValidationReport) -> None:
    """Pretty-print a validation report to console."""
    table = Table(title="Documentation Validation Report")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Details")

    s_status = "PASS" if not report.structural_errors else "FAIL"
    table.add_row(
        "Structural",
        f"[green]{s_status}[/green]" if s_status == "PASS" else f"[red]{s_status}[/red]",
        f"missing docs: {report.stats.get('program_docs_missing', 0)}, "
        f"broken links: {report.stats.get('broken_links', 0)}, "
        f"empty/missing sections: "
        f"{report.stats.get('empty_sections', 0) + report.stats.get('missing_sections', 0)}",
    )

    f_status = "PASS" if not report.factual_errors else "FAIL"
    table.add_row(
        "Factual",
        f"[green]{f_status}[/green]" if f_status == "PASS" else f"[red]{f_status}[/red]",
        f"unknown identifier refs: {report.stats.get('unknown_identifier_refs', 0)}",
    )

    expected = report.stats.get("coverage_expected_refs", 0)
    missing = report.stats.get("coverage_missing_refs", 0)
    pct = 100.0 * (expected - missing) / expected if expected else 100.0
    c_status = "PASS" if missing == 0 else "FAIL"
    table.add_row(
        "Coverage",
        f"[green]{c_status}[/green]" if c_status == "PASS" else f"[red]{c_status}[/red]",
        f"{expected - missing}/{expected} references covered ({pct:.1f}%)",
    )

    console.print(table)

    # Show first 10 issues per category
    if report.structural_errors:
        console.print("\n[red]Structural Errors:[/red]")
        for e in report.structural_errors[:10]:
            console.print(f"  - {e}")
    if report.structural_warnings:
        console.print(f"\n[yellow]Structural Warnings ({len(report.structural_warnings)}):[/yellow]")
        for w in report.structural_warnings[:10]:
            console.print(f"  - {w}")
    if report.factual_errors:
        console.print(f"\n[red]Factual Errors ({len(report.factual_errors)}):[/red]")
        for e in report.factual_errors[:10]:
            console.print(f"  - {e}")
    if report.coverage_gaps:
        console.print(f"\n[yellow]Coverage Gaps ({len(report.coverage_gaps)}):[/yellow]")
        for g in report.coverage_gaps[:10]:
            console.print(f"  - {g}")


def write_report(report: ValidationReport, output_path: str) -> None:
    """Write the validation report as JSON."""
    Path(output_path).write_text(
        json.dumps(report.to_dict(), indent=2),
        encoding="utf-8",
    )
    console.print(f"[green]Report written to {output_path}[/green]")


# ───────────────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Validate generated COBOL docs")
    parser.add_argument("--db", default="data/cobol_knowledge.db", help="SQLite DB path")
    parser.add_argument("--docs", default="docs", help="Generated docs directory")
    parser.add_argument("--out", default="docs/validation_report.json", help="JSON report output")
    args = parser.parse_args()

    report = validate_docs(args.db, args.docs)
    print_report(report)
    write_report(report, args.out)

    raise SystemExit(0 if report.passed else 1)
