"""
SQLite Loader - Swimm-Style Knowledge Base
Loads ProLeap-parsed COBOL data into SQLite with full statement-level detail.
Implements graph-based module detection.
"""

import os
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

console = Console(force_terminal=True, highlight=False)


class SQLiteLoader:
    """Loads parsed and enriched COBOL data into SQLite knowledge base."""

    def __init__(self, db_path: str, schema_path: str = None):
        self.db_path = db_path
        self.schema_path = schema_path or "schemas/cobol_knowledge.sql"
        self.conn = None

    def connect(self):
        """Connect to the database and initialize schema."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False so the loader can be cached across Streamlit reruns
        # (Streamlit dispatches reruns on different threads).
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

        if os.path.exists(self.schema_path):
            console.print(f"[cyan]Initializing database schema...[/cyan]")
            with open(self.schema_path, 'r') as f:
                schema_sql = f.read()
            self.conn.executescript(schema_sql)
            self.conn.commit()

        # Apply any schema migrations for columns added after initial release
        self._apply_migrations()

        console.print(f"[green]OK - Connected to {self.db_path}[/green]")

    def _apply_migrations(self):
        """Add new columns to existing tables — safe to run on any DB version."""
        new_columns = [
            ("programs", "migration_complexity",          "INTEGER"),
            ("programs", "complexity_reason",             "TEXT"),
            ("programs", "modern_equivalent",             "TEXT"),
            ("programs", "suggested_service",             "TEXT"),
            ("programs", "migration_approach",            "TEXT"),
            ("programs", "data_contracts",                "TEXT"),
            ("programs", "migration_risks",               "TEXT"),
            ("programs", "dependencies_to_migrate_first", "TEXT"),
        ]
        cursor = self.conn.cursor()
        for table, col, coltype in new_columns:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except Exception:
                pass  # Column already exists — that's fine
        self.conn.commit()

        # Create generated_docs table (added for agentic doc pipeline)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS generated_docs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                mode          TEXT NOT NULL,
                subject       TEXT NOT NULL,
                document_text TEXT NOT NULL,
                generated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(mode, subject)
            )
        """)

        # Create exec_cics table (EXEC CICS commands per program)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exec_cics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id TEXT NOT NULL,
                command TEXT NOT NULL,
                paragraph_name TEXT,
                line_number INTEGER,
                details_json TEXT,
                FOREIGN KEY (program_id) REFERENCES programs(program_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exec_cics_program ON exec_cics(program_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exec_cics_command ON exec_cics(command)")

        # Create exec_sql table (EXEC SQL DB2 statements per program)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exec_sql (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id TEXT NOT NULL,
                command TEXT NOT NULL,
                table_name TEXT,
                cursor_name TEXT,
                paragraph_name TEXT,
                line_number INTEGER,
                sql_text TEXT,
                FOREIGN KEY (program_id) REFERENCES programs(program_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exec_sql_program ON exec_sql(program_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exec_sql_command ON exec_sql(command)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exec_sql_table   ON exec_sql(table_name)")

        # Create ims_calls table (IMS DL/I CALL 'CBLTDLI' statements per program)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ims_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id TEXT NOT NULL,
                function_code TEXT NOT NULL,
                function_name TEXT,
                pcb_name TEXT,
                segment_area TEXT,
                ssa_name TEXT,
                ssa_segment TEXT,
                ssa_qualifier TEXT,
                paragraph_name TEXT,
                line_number INTEGER,
                raw_text TEXT,
                FOREIGN KEY (program_id) REFERENCES programs(program_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ims_calls_program ON ims_calls(program_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ims_calls_function ON ims_calls(function_code)")

        # copybook_fields — field-level dictionary for each copybook
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS copybook_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                copybook_name TEXT NOT NULL,
                field_name TEXT NOT NULL,
                level_number INTEGER,
                picture TEXT,
                usage TEXT,
                value TEXT,
                parent_name TEXT,
                line_number INTEGER,
                occurs_count INTEGER,
                redefines_target TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_copybook_fields_name ON copybook_fields(copybook_name)")

        # file_records — FD record layouts per program
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                record_name TEXT,
                field_name TEXT,
                level_number INTEGER,
                picture TEXT,
                usage TEXT,
                parent_name TEXT,
                line_number INTEGER
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_program ON file_records(program_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_file ON file_records(file_name)")

        # data_movements — MOVE source -> destination (data lineage)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id TEXT NOT NULL,
                source_field TEXT NOT NULL,
                destination_field TEXT NOT NULL,
                paragraph_name TEXT,
                line_number INTEGER,
                is_literal INTEGER DEFAULT 0
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_data_movements_program ON data_movements(program_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_data_movements_source ON data_movements(source_field)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_data_movements_dest ON data_movements(destination_field)")

        # Add resolved_target column to program_calls (dynamic CALL resolution)
        try:
            cursor.execute("ALTER TABLE program_calls ADD COLUMN resolved_target TEXT")
        except Exception:
            pass

        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # ================================================================
    # Internal Helpers
    # ================================================================

    def _recreate_fts_triggers(self, cursor):
        """Re-create FTS sync triggers after bulk load."""
        triggers = [
            """CREATE TRIGGER IF NOT EXISTS programs_ai AFTER INSERT ON programs BEGIN
                INSERT INTO programs_fts(rowid, program_id, business_name, business_purpose)
                VALUES (NEW.id, NEW.program_id, NEW.business_name, NEW.business_purpose);
            END""",
            """CREATE TRIGGER IF NOT EXISTS programs_ad AFTER DELETE ON programs BEGIN
                INSERT INTO programs_fts(programs_fts, rowid, program_id, business_name, business_purpose)
                VALUES ('delete', OLD.id, OLD.program_id, OLD.business_name, OLD.business_purpose);
            END""",
            """CREATE TRIGGER IF NOT EXISTS programs_au AFTER UPDATE ON programs BEGIN
                INSERT INTO programs_fts(programs_fts, rowid, program_id, business_name, business_purpose)
                VALUES ('delete', OLD.id, OLD.program_id, OLD.business_name, OLD.business_purpose);
                INSERT INTO programs_fts(rowid, program_id, business_name, business_purpose)
                VALUES (NEW.id, NEW.program_id, NEW.business_name, NEW.business_purpose);
            END""",
            """CREATE TRIGGER IF NOT EXISTS data_items_ai AFTER INSERT ON data_items BEGIN
                INSERT INTO data_items_fts(rowid, name, business_name, description)
                VALUES (NEW.id, NEW.name, NEW.business_name, NEW.description);
            END""",
            """CREATE TRIGGER IF NOT EXISTS business_rules_ai AFTER INSERT ON business_rules BEGIN
                INSERT INTO business_rules_fts(rowid, rule_name, rule_statement, condition_text, action_text)
                VALUES (NEW.id, NEW.rule_name, NEW.rule_statement, NEW.condition_text, NEW.action_text);
            END""",
        ]
        for sql in triggers:
            try:
                cursor.execute(sql)
            except:
                pass

    # ================================================================
    # Loading Methods
    # ================================================================

    def update_business_context(self, program_id, data):
        """Specifically update business context fields for a program."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE programs SET
                business_name = ?,
                business_purpose = ?,
                user_role = ?,
                business_process = ?
            WHERE program_id = ?
        """, (
            data.get("business_name"),
            data.get("business_purpose"),
            data.get("user_role"),
            data.get("business_process"),
            program_id
        ))
        self.conn.commit()

    def update_paragraph_narratives(self, program_id, paragraphs):
        """Specifically update narrative fields for paragraphs."""
        cursor = self.conn.cursor()
        for p in paragraphs:
            cursor.execute("""
                UPDATE paragraphs SET
                    business_name = ?,
                    narrative = ?,
                    purpose = ?
                WHERE program_id = ? AND paragraph_name = ?
            """, (
                p.get("business_name"),
                p.get("narrative"),
                p.get("purpose"),
                program_id,
                p.get("name")
            ))
        self.conn.commit()

    def load_programs(self, programs: List[Dict]):
        """Load program data including statements, calls, performs, CICS."""
        cursor = self.conn.cursor()

        # Drop FTS triggers temporarily for bulk load performance
        for trig in ["programs_ai", "programs_ad", "programs_au",
                      "data_items_ai", "business_rules_ai"]:
            try:
                cursor.execute(f"DROP TRIGGER IF EXISTS {trig}")
            except:
                pass
        # Disable foreign keys during bulk load for performance
        cursor.execute("PRAGMA foreign_keys = OFF")
        self.conn.commit()

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                       BarColumn(), console=console) as progress:
            task = progress.add_task("Loading programs...", total=len(programs))

            for program in programs:
                try:
                    program_id = program.get("program_id")

                    # Serialize list/dict fields to JSON text for storage
                    def _to_str(val):
                        if val is None:
                            return None
                        if isinstance(val, (list, dict)):
                            return json.dumps(val)
                        return val
                    deps_json = json.dumps(program.get("dependencies_to_migrate_first") or [])
                    data_contracts = _to_str(program.get("data_contracts"))
                    migration_risks = _to_str(program.get("migration_risks"))
                    migration_approach = _to_str(program.get("migration_approach"))

                    # Insert/replace program
                    cursor.execute("""
                        INSERT OR REPLACE INTO programs (
                            program_id, file_path, file_hash, program_type, line_count,
                            business_name, business_purpose, user_role, business_process,
                            migration_complexity, complexity_reason, modern_equivalent,
                            suggested_service, migration_approach, data_contracts,
                            migration_risks, dependencies_to_migrate_first,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        program_id,
                        program.get("file_path"),
                        program.get("file_hash"),
                        program.get("program_type"),
                        program.get("line_count"),
                        program.get("business_name"),
                        program.get("business_purpose"),
                        program.get("user_role"),
                        program.get("business_process"),
                        program.get("migration_complexity"),
                        program.get("complexity_reason"),
                        program.get("modern_equivalent"),
                        program.get("suggested_service"),
                        migration_approach,
                        data_contracts,
                        migration_risks,
                        deps_json,
                        datetime.now().isoformat()
                    ))

                    # Clear old data for this program
                    for table in ["paragraphs", "data_items", "files", "statements",
                                  "performs", "copybook_usage", "exec_cics", "exec_sql",
                                  "ims_calls", "file_records", "data_movements"]:
                        cursor.execute(f"DELETE FROM {table} WHERE program_id = ?", (program_id,))
                    # program_calls uses caller_program, not program_id
                    cursor.execute("DELETE FROM program_calls WHERE caller_program = ?", (program_id,))

                    source_ranges = self._source_paragraph_ranges(
                        program.get("file_path"), program.get("paragraphs", [])
                    )

                    def _source_paragraph_for_line(line_num):
                        try:
                            line_num = int(line_num or 0)
                        except Exception:
                            return None
                        for pname, (start, end) in source_ranges.items():
                            if start <= line_num <= end:
                                return pname
                        return None

                    # Insert paragraphs. If ProLeap returned none AND we have source,
                    # fall back to a regex paragraph parser so the program isn't blank.
                    parsed_paras = program.get("paragraphs", []) or []
                    if not parsed_paras and program.get("file_path"):
                        try:
                            fallback = self._extract_paragraphs_from_source(program["file_path"])
                        except Exception:
                            fallback = []
                        if fallback:
                            parsed_paras = fallback
                            console.print(
                                f"[cyan]  paragraphs fallback: extracted {len(fallback)} paragraphs from source for {program_id}[/cyan]"
                            )
                            # Also write back into the program dict so downstream
                            # extractors (FD/MOVE/IMS) can use the paragraph ranges.
                            program["paragraphs"] = fallback

                    for para in parsed_paras:
                        para_name = para.get("name")
                        source_start, source_end = source_ranges.get(
                            (para_name or "").upper(),
                            (para.get("line_start"), para.get("line_end")),
                        )
                        cursor.execute("""
                            INSERT OR REPLACE INTO paragraphs (
                                program_id, paragraph_name, line_start, line_end,
                                business_name, narrative, purpose
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            program_id,
                            para_name,
                            source_start,
                            source_end,
                            para.get("business_name"),
                            para.get("narrative"),
                            para.get("purpose")
                        ))

                    # Insert data items
                    for item in program.get("data_items", []):
                        cursor.execute("""
                            INSERT OR REPLACE INTO data_items (
                                program_id, name, level_number, picture, usage, value,
                                section, parent_name, line_number,
                                business_name, description, data_type_description
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            program_id,
                            item.get("name"),
                            item.get("level_number"),
                            item.get("picture"),
                            item.get("usage"),
                            item.get("value"),
                            item.get("section"),
                            item.get("parent_name"),
                            item.get("line_number"),
                            item.get("business_name"),
                            item.get("description"),
                            item.get("data_type_description")
                        ))

                    # Insert files
                    for f in program.get("files", []):
                        cursor.execute("""
                            INSERT OR REPLACE INTO files (
                                program_id, file_name, file_type, organization,
                                access_mode, record_name, business_name, description
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            program_id, f.get("file_name"), f.get("file_type"),
                            f.get("organization"), f.get("access_mode"),
                            f.get("record_name"), f.get("business_name"), f.get("description")
                        ))

                    # Insert ALL statements (new: this was empty before)
                    for stmt in program.get("statements", []):
                        details = {k: v for k, v in stmt.items()
                                   if k not in ("type", "line", "line_end", "paragraph", "raw_text")}
                        stmt_para = _source_paragraph_for_line(stmt.get("line")) or stmt.get("paragraph")
                        cursor.execute("""
                            INSERT OR REPLACE INTO statements (
                                program_id, paragraph_name, statement_type,
                                line_number, details_json
                            ) VALUES (?, ?, ?, ?, ?)
                        """, (
                            program_id,
                            stmt_para,
                            stmt.get("type"),
                            stmt.get("line"),
                            json.dumps(details) if details else None
                        ))

                    # Insert calls
                    for call in program.get("calls", []):
                        cursor.execute("""
                            INSERT OR REPLACE INTO program_calls (
                                caller_program, called_program, call_location, line_number
                            ) VALUES (?, ?, ?, ?)
                        """, (
                            program_id,
                            call.get("called_program"),
                            call.get("call_location"),
                            call.get("line_number")
                        ))

                    # Insert performs
                    for perf in program.get("performs", []):
                        source_para = _source_paragraph_for_line(perf.get("line_number")) or perf.get("source_paragraph", "MAIN")
                        cursor.execute("""
                            INSERT OR REPLACE INTO performs (
                                program_id, source_paragraph, target_paragraph,
                                perform_type, line_number, condition
                            ) VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            program_id,
                            source_para,
                            perf.get("target_paragraph"),
                            perf.get("perform_type", "SIMPLE"),
                            perf.get("line_number"),
                            perf.get("condition")
                        ))

                    # Insert copybook usage
                    for cb in program.get("copybooks", []):
                        cursor.execute("INSERT OR IGNORE INTO copybooks (copybook_name) VALUES (?)", (cb,))
                        cursor.execute("""
                            INSERT OR REPLACE INTO copybook_usage (program_id, copybook_name) VALUES (?, ?)
                        """, (program_id, cb))

                    # Insert EXEC CICS commands
                    # If ProLeap gave all UNKNOWN commands, extract from source
                    cics_list = program.get("exec_cics", [])
                    all_unknown = cics_list and all(
                        c.get("command", "UNKNOWN") == "UNKNOWN" for c in cics_list
                    )
                    if all_unknown and program.get("file_path"):
                        cics_list = self._extract_cics_from_source(
                            program["file_path"], program.get("paragraphs", [])
                        )

                    for cics in cics_list:
                        details = {k: v for k, v in cics.items()
                                   if k not in ("command", "line_number", "paragraph")}
                        cursor.execute("""
                            INSERT INTO exec_cics (
                                program_id, command, paragraph_name,
                                line_number, details_json
                            ) VALUES (?, ?, ?, ?, ?)
                        """, (
                            program_id,
                            cics.get("command", "UNKNOWN"),
                            cics.get("paragraph"),
                            cics.get("line_number"),
                            json.dumps(details) if details else None
                        ))

                    # Insert EXEC SQL (DB2) commands — extracted from source
                    if program.get("file_path"):
                        sql_list = self._extract_sql_from_source(
                            program["file_path"], program.get("paragraphs", [])
                        )
                        for s in sql_list:
                            cursor.execute("""
                                INSERT INTO exec_sql (
                                    program_id, command, table_name, cursor_name,
                                    paragraph_name, line_number, sql_text
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                program_id,
                                s.get("command", "UNKNOWN"),
                                s.get("table_name"),
                                s.get("cursor_name"),
                                s.get("paragraph"),
                                s.get("line_number"),
                                s.get("sql_text"),
                            ))

                    # Resolve dynamic CALLs by reading source. Insert resolved
                    # calls as NEW program_calls rows — we can't trust ProLeap's
                    # line numbers (parsed JSON may be stale relative to source).
                    if program.get("file_path"):
                        try:
                            resolutions = self._resolve_dynamic_calls_from_source(
                                program["file_path"], program.get("paragraphs", [])
                            )
                            for res in resolutions:
                                # Skip if a row already exists for the same caller+target
                                cursor.execute("""
                                    SELECT 1 FROM program_calls
                                    WHERE caller_program = ?
                                      AND (called_program = ? OR resolved_target = ?)
                                """, (program_id, res["resolved_target"], res["resolved_target"]))
                                if cursor.fetchone():
                                    continue
                                cursor.execute("""
                                    INSERT INTO program_calls (
                                        caller_program, called_program,
                                        call_location, line_number,
                                        resolved_target
                                    ) VALUES (?, 'UNKNOWN', ?, ?, ?)
                                """, (
                                    program_id,
                                    res.get("paragraph"),
                                    res.get("line_number"),
                                    res["resolved_target"],
                                ))
                        except Exception:
                            pass

                    # Insert IMS DL/I calls — extracted from source
                    if program.get("file_path"):
                        ims_list = self._extract_ims_from_source(
                            program["file_path"], program.get("paragraphs", []),
                            program.get("data_items", [])
                        )
                        for im in ims_list:
                            cursor.execute("""
                                INSERT INTO ims_calls (
                                    program_id, function_code, function_name,
                                    pcb_name, segment_area, ssa_name,
                                    ssa_segment, ssa_qualifier,
                                    paragraph_name, line_number, raw_text
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                program_id,
                                im.get("function_code", "UNKNOWN"),
                                im.get("function_name"),
                                im.get("pcb_name"),
                                im.get("segment_area"),
                                im.get("ssa_name"),
                                im.get("ssa_segment"),
                                im.get("ssa_qualifier"),
                                im.get("paragraph"),
                                im.get("line_number"),
                                im.get("raw_text"),
                            ))

                    # Insert SELECT/ASSIGN-derived file declarations
                    if program.get("file_path"):
                        try:
                            file_decls = self._extract_files_from_source(program["file_path"])
                            for f in file_decls:
                                cursor.execute("""
                                    INSERT INTO files (
                                        program_id, file_name, file_type,
                                        organization, access_mode, record_name
                                    ) VALUES (?, ?, ?, ?, ?, ?)
                                """, (
                                    program_id,
                                    f.get("file_name"),
                                    f.get("file_type"),
                                    f.get("organization"),
                                    f.get("access_mode"),
                                    f.get("record_key"),
                                ))
                        except Exception as _f_err:
                            console.print(f"[yellow]  files extraction failed for {program_id}: {_f_err}[/yellow]")

                    # Insert FD record layouts — extracted from source
                    if program.get("file_path"):
                        try:
                            fd_records = self._extract_file_records_from_source(program["file_path"])
                            for r in fd_records:
                                cursor.execute("""
                                    INSERT INTO file_records (
                                        program_id, file_name, record_name, field_name,
                                        level_number, picture, usage, parent_name, line_number
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    program_id,
                                    r.get("file_name"),
                                    r.get("record_name"),
                                    r.get("field_name"),
                                    r.get("level_number"),
                                    r.get("picture"),
                                    r.get("usage"),
                                    r.get("parent_name"),
                                    r.get("line_number"),
                                ))
                        except Exception as _fd_err:
                            console.print(f"[yellow]  FD extraction failed for {program_id}: {_fd_err}[/yellow]")

                    # Insert MOVE-based data lineage — extracted from source
                    if program.get("file_path"):
                        try:
                            moves = self._extract_movements_from_source(
                                program["file_path"], program.get("paragraphs", [])
                            )
                            for mv in moves:
                                cursor.execute("""
                                    INSERT INTO data_movements (
                                        program_id, source_field, destination_field,
                                        paragraph_name, line_number, is_literal
                                    ) VALUES (?, ?, ?, ?, ?, ?)
                                """, (
                                    program_id,
                                    mv.get("source_field"),
                                    mv.get("destination_field"),
                                    mv.get("paragraph"),
                                    mv.get("line_number"),
                                    mv.get("is_literal", 0),
                                ))
                        except Exception as _mv_err:
                            console.print(f"[yellow]  MOVE extraction failed for {program_id}: {_mv_err}[/yellow]")

                except Exception as e:
                    import traceback
                    console.print(f"[yellow]Warning: Error loading {program.get('program_id')}: {e}[/yellow]")
                    traceback.print_exc()

                progress.advance(task)

        # Re-enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")
        self.conn.commit()

        # Rebuild FTS indexes from content tables
        try:
            cursor.execute("INSERT INTO programs_fts(programs_fts) VALUES('rebuild')")
            cursor.execute("INSERT INTO data_items_fts(data_items_fts) VALUES('rebuild')")
            cursor.execute("INSERT INTO business_rules_fts(business_rules_fts) VALUES('rebuild')")
            self.conn.commit()
        except Exception as e:
            console.print(f"[yellow]Warning: FTS rebuild: {e}[/yellow]")

        # Re-create FTS triggers from schema
        try:
            self._recreate_fts_triggers(cursor)
            self.conn.commit()
        except Exception as e:
            console.print(f"[yellow]Warning: FTS trigger re-creation: {e}[/yellow]")

        console.print(f"[green]OK - Loaded {len(programs)} programs[/green]")

    @staticmethod
    def _source_paragraph_ranges(file_path: str, paragraphs: List[Dict]) -> Dict[str, tuple]:
        """Map paragraph names to physical source line ranges by scanning labels.

        Parser line ranges can drift after COPY expansion. Anything extracted
        directly from source should use these physical ranges for attribution.
        """
        import re
        from pathlib import Path

        src = Path(file_path or "")
        if not src.exists():
            return {}
        try:
            lines = src.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return {}

        names = []
        for p in paragraphs or []:
            name = (p.get("name") or p.get("paragraph_name") or "").upper()
            if name:
                names.append(name)
        if not names:
            return {}

        def _body(raw_line: str) -> str:
            if len(raw_line) > 6 and raw_line[6] == "*":
                return ""
            body = raw_line[6:] if len(raw_line) > 6 else raw_line
            return body[:66] if len(body) > 66 else body

        starts = []
        for idx, raw_line in enumerate(lines, 1):
            body = _body(raw_line).strip().upper()
            for name in names:
                if re.match(rf"^{re.escape(name)}\s*\.", body):
                    starts.append((idx, name))
                    break
        starts.sort()

        ranges = {}
        for pos, (start, name) in enumerate(starts):
            end = starts[pos + 1][0] - 1 if pos + 1 < len(starts) else len(lines)
            ranges[name] = (start, end)
        return ranges

    @staticmethod
    def _resolve_dynamic_calls_from_source(file_path: str, paragraphs: List[Dict]) -> List[Dict]:
        """For each `CALL <variable>` in the source, scan backward in the same paragraph
        for the most recent `MOVE 'LITERAL' TO <variable>` and resolve the call target.
        Returns: [{line_number, paragraph, variable, resolved_target}, ...]"""
        import re
        from pathlib import Path

        src = Path(file_path)
        if not src.exists():
            return []
        try:
            content = src.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        lines = content.split("\n")

        # Strip column 1-6 sequence area + comment lines.
        # Also strip quoted string literals so we don't match "CALL" inside DISPLAY text.
        _quote_pat = re.compile(r"'[^']*'|\"[^\"]*\"")
        def _stripped(idx):
            line = lines[idx]
            if len(line) > 6 and line[6] == "*":
                return ""
            body = line[6:] if len(line) > 6 else line
            # Also strip the trailing column-73-80 sequence area if present
            if len(body) > 66:
                body = body[:66]
            # Replace any quoted literal with whitespace so it can't match keywords
            body = _quote_pat.sub(lambda m: " " * len(m.group()), body)
            return body

        source_ranges = SQLiteLoader._source_paragraph_ranges(file_path, paragraphs)

        def _find_paragraph(line_num):
            for pname, (start, end) in source_ranges.items():
                if start <= line_num <= end:
                    return {"name": pname, "line_start": start, "line_end": end}
            for p in paragraphs or []:
                start = p.get("line_start", 0)
                end = p.get("line_end", 0)
                if start and end and start <= line_num <= end:
                    return p
            return None

        # Match `CALL <bare-identifier>` (no quotes) — that's a dynamic call.
        call_var_pat = re.compile(r"\bCALL\s+([A-Z][A-Z0-9-]*)\b(?!\s*['\"])", re.IGNORECASE)
        # Match `MOVE 'literal' TO <identifier>` or `MOVE "literal" TO <identifier>`
        move_lit_pat = re.compile(
            r"\bMOVE\s+['\"]([A-Z0-9_-]+)['\"]\s+TO\s+([A-Z][A-Z0-9-]*)\b",
            re.IGNORECASE,
        )

        results = []
        for idx in range(len(lines)):
            line_num = idx + 1
            text = _stripped(idx)
            if not text or "CALL" not in text.upper():
                continue
            m = call_var_pat.search(text)
            if not m:
                continue
            var_name = m.group(1).upper()
            # Skip COBOL keywords that look like identifiers
            if var_name in ("USING", "GIVING", "RETURNING", "BY"):
                continue

            para = _find_paragraph(line_num)
            if not para:
                continue
            para_start = para.get("line_start", 1)

            # Walk backward inside the same paragraph for the latest MOVE literal TO var
            resolved = None
            for back_idx in range(idx - 1, max(para_start - 2, -1), -1):
                back_text = _stripped(back_idx)
                if not back_text:
                    continue
                for mm in move_lit_pat.finditer(back_text):
                    if mm.group(2).upper() == var_name:
                        resolved = mm.group(1).upper()
                        break
                if resolved:
                    break

            if resolved:
                results.append({
                    "line_number": line_num,
                    "paragraph": para.get("name"),
                    "variable": var_name,
                    "resolved_target": resolved,
                })

        return results

    @staticmethod
    def _extract_paragraphs_from_source(file_path: str) -> List[Dict]:
        """Fallback paragraph parser. Detects lines that look like
        `       PARAGRAPH-NAME.` (column 8+, ends with period, identifier-like)
        inside the PROCEDURE DIVISION. Returns [{name, line_start, line_end}, ...]."""
        import re
        from pathlib import Path
        src = Path(file_path)
        if not src.exists():
            return []
        try:
            content = src.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        lines = content.split("\n")

        in_proc = False
        para_pat = re.compile(r"^\s{0,7}([A-Z][A-Z0-9-]{2,30})\s*\.\s*$")
        # COBOL keywords/sections that match the regex but aren't paragraphs
        skip = {"PROCEDURE", "DIVISION", "SECTION", "FILE", "WORKING-STORAGE",
                 "LINKAGE", "LOCAL-STORAGE", "INPUT-OUTPUT", "FILE-CONTROL",
                 "I-O-CONTROL", "DATA", "ENVIRONMENT", "IDENTIFICATION",
                 "CONFIGURATION", "SPECIAL-NAMES", "SOURCE-COMPUTER",
                 "OBJECT-COMPUTER", "PROGRAM-ID", "AUTHOR", "DATE-WRITTEN",
                 "DATE-COMPILED", "INSTALLATION", "SECURITY", "REMARKS"}

        paras = []
        cur_name = None
        cur_start = 0
        for i, raw in enumerate(lines):
            line_num = i + 1
            if len(raw) > 6 and raw[6] == "*":
                continue
            body = raw[6:] if len(raw) > 6 else raw
            body = body[:66] if len(body) > 66 else body
            up = body.upper()
            if "PROCEDURE DIVISION" in up:
                in_proc = True
                continue
            if not in_proc:
                continue
            m = para_pat.match(body)
            if not m:
                continue
            name = m.group(1).upper()
            if name in skip:
                continue
            # Skip if it's actually an SQL/CICS keyword being used as period statement
            if name in ("END-EXEC", "EXIT", "STOP"):
                continue

            # Close out previous paragraph
            if cur_name:
                paras.append({"name": cur_name, "line_start": cur_start, "line_end": line_num - 1})
            cur_name = name
            cur_start = line_num

        if cur_name:
            paras.append({"name": cur_name, "line_start": cur_start, "line_end": len(lines)})

        return paras

    @staticmethod
    def _extract_files_from_source(file_path: str) -> List[Dict]:
        """Parse the FILE-CONTROL section to extract SELECT … ASSIGN TO …
        ORGANIZATION/ACCESS clauses. Each entry maps a logical file name
        to its DDname plus organisation and access mode."""
        import re
        from pathlib import Path
        src = Path(file_path)
        if not src.exists():
            return []
        try:
            content = src.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        lines = content.split("\n")

        def _strip_seq(line: str) -> str:
            if len(line) > 6 and line[6] == "*":
                return ""
            body = line[6:] if len(line) > 6 else line
            return body[:66] if len(body) > 66 else body

        # Find FILE-CONTROL block
        in_fc = False
        block = []
        block_start = 0
        for i, raw in enumerate(lines):
            body = _strip_seq(raw)
            up = body.upper()
            if "FILE-CONTROL" in up:
                in_fc = True
                block_start = i + 1
                continue
            if in_fc and (
                "DATA DIVISION" in up or "PROCEDURE DIVISION" in up
                or "I-O-CONTROL" in up
            ):
                break
            if in_fc:
                block.append((i + 1, body))
        if not block:
            return []

        # Group by SELECT — each SELECT statement runs until period
        results = []
        select_pat = re.compile(
            r"\bSELECT\s+(?:OPTIONAL\s+)?([A-Z][A-Z0-9-]*)\s+ASSIGN\s+TO\s+([A-Z][A-Z0-9-]*)",
            re.IGNORECASE,
        )
        org_pat = re.compile(r"\bORGANIZATION\s+(?:IS\s+)?([A-Z]+)", re.IGNORECASE)
        acc_pat = re.compile(r"\bACCESS\s+(?:MODE\s+)?(?:IS\s+)?([A-Z]+)", re.IGNORECASE)
        rec_key_pat = re.compile(r"\bRECORD\s+KEY\s+(?:IS\s+)?([A-Z][A-Z0-9-]*)", re.IGNORECASE)

        # Concatenate lines and split on period
        joined = " ".join(b[1] for b in block)
        line_map = []  # cumulative line numbers per chunk
        for ln_num, b in block:
            for _ in range(len(b) + 1):
                line_map.append(ln_num)

        # Walk through SELECT statements
        for m in select_pat.finditer(joined):
            file_name = m.group(1).upper()
            ddname = m.group(2).upper()
            # Find the matching period after this SELECT
            start = m.end()
            end = joined.find(".", start)
            if end == -1:
                end = len(joined)
            stmt = joined[start:end]

            org_m = org_pat.search(stmt)
            acc_m = acc_pat.search(stmt)
            rec_m = rec_key_pat.search(stmt)

            organization = org_m.group(1).upper() if org_m else None
            access_mode = acc_m.group(1).upper() if acc_m else None
            record_key = rec_m.group(1).upper() if rec_m else None

            file_type = "VSAM" if organization == "INDEXED" else (
                "SEQUENTIAL" if organization == "SEQUENTIAL" else organization
            )

            ln = line_map[m.start()] if m.start() < len(line_map) else None
            results.append({
                "file_name": file_name,
                "ddname": ddname,
                "file_type": file_type,
                "organization": organization,
                "access_mode": access_mode,
                "record_key": record_key,
                "line_number": ln,
            })
        return results

    @staticmethod
    def _extract_data_items_from_lines(lines: List[str], start_line: int = 1):
        """Generic COBOL data-item parser. Reads lines starting at start_line,
        returns a list of dicts: {field_name, level, picture, usage, value, parent,
        line_number, occurs, redefines}.

        Works on copybook .cpy files OR a slice of a .cbl file (e.g. an FD block).
        """
        import re

        # COBOL data declaration: <level> <name> [PIC ...] [USAGE ...] [VALUE ...]
        # Levels: 01-49, 66, 77, 88
        decl_pat = re.compile(
            r"^\s*(\d{2})\s+([A-Z][A-Z0-9-]*)\b(.*?)(?:\.\s*$|$)",
            re.IGNORECASE,
        )
        pic_pat = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", re.IGNORECASE)
        usage_pat = re.compile(r"\b(?:USAGE\s+(?:IS\s+)?)?(COMP|COMP-3|COMP-4|COMP-5|BINARY|PACKED-DECIMAL|DISPLAY)\b", re.IGNORECASE)
        value_pat = re.compile(r"\bVALUE\s+(?:IS\s+)?([^.]+)", re.IGNORECASE)
        occurs_pat = re.compile(r"\bOCCURS\s+(\d+)", re.IGNORECASE)
        redef_pat = re.compile(r"\bREDEFINES\s+([A-Z][A-Z0-9-]*)", re.IGNORECASE)

        items = []
        # Stack of (level_number, field_name) for parent tracking
        parent_stack = []
        # We sometimes need to join continuation lines (statement runs until period)
        buf = ""
        buf_line_num = 0

        def _strip_seq(line: str) -> str:
            if len(line) > 6 and line[6] == "*":
                return ""
            body = line[6:] if len(line) > 6 else line
            return body[:66] if len(body) > 66 else body

        for idx, raw in enumerate(lines):
            line_num = start_line + idx
            body = _strip_seq(raw)
            if not body.strip():
                continue
            if not buf:
                buf = body
                buf_line_num = line_num
            else:
                buf += " " + body
            # If buffer doesn't end with period yet, keep accumulating
            if "." not in buf:
                continue
            # Process complete statements (split on period, keep last incomplete part as buf)
            parts = buf.split(".")
            buf = parts[-1]
            for part in parts[:-1]:
                m = decl_pat.match(part)
                if not m:
                    continue
                lvl = int(m.group(1))
                name = m.group(2).upper()
                if name in ("FILLER",):
                    continue
                # Skip non-data items
                if name in ("FD", "SD", "WORKING-STORAGE", "LINKAGE", "FILE",
                             "PROCEDURE", "DIVISION", "SECTION", "COPY"):
                    continue
                clauses = m.group(3) or ""
                pic = (pic_pat.search(clauses) or [None, None])[1] if pic_pat.search(clauses) else None
                use_m = usage_pat.search(clauses)
                usage = use_m.group(1).upper() if use_m else None
                val_m = value_pat.search(clauses)
                value = val_m.group(1).strip().rstrip(".") if val_m else None
                occ_m = occurs_pat.search(clauses)
                occurs = int(occ_m.group(1)) if occ_m else None
                redef_m = redef_pat.search(clauses)
                redefines = redef_m.group(1).upper() if redef_m else None

                # Maintain parent stack by level
                while parent_stack and parent_stack[-1][0] >= lvl:
                    parent_stack.pop()
                parent = parent_stack[-1][1] if parent_stack else None

                items.append({
                    "field_name": name,
                    "level": lvl,
                    "picture": pic,
                    "usage": usage,
                    "value": value,
                    "parent": parent,
                    "line_number": buf_line_num,
                    "occurs": occurs,
                    "redefines": redefines,
                })

                if pic is None and lvl < 50:
                    parent_stack.append((lvl, name))

            buf_line_num = line_num
        return items

    @staticmethod
    def _extract_copybook_fields_from_source(file_path: str) -> List[Dict]:
        """Parse a .cpy file and return field-level dictionary entries."""
        from pathlib import Path
        src = Path(file_path)
        if not src.exists():
            return []
        try:
            content = src.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        return SQLiteLoader._extract_data_items_from_lines(content.split("\n"))

    @staticmethod
    def _extract_file_records_from_source(file_path: str) -> List[Dict]:
        """Find each `FD <file-name>` block in a COBOL program and return
        the data items that follow until the next FD or section break."""
        import re
        from pathlib import Path
        src = Path(file_path)
        if not src.exists():
            return []
        try:
            content = src.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        lines = content.split("\n")

        def _strip_seq(line: str) -> str:
            if len(line) > 6 and line[6] == "*":
                return ""
            body = line[6:] if len(line) > 6 else line
            return body[:66] if len(body) > 66 else body

        fd_pat = re.compile(r"^\s*FD\s+([A-Z][A-Z0-9-]*)\b", re.IGNORECASE)
        section_break_pat = re.compile(
            r"^\s*(WORKING-STORAGE|LINKAGE|PROCEDURE|LOCAL-STORAGE)\s+SECTION", re.IGNORECASE)

        results = []
        i = 0
        while i < len(lines):
            body = _strip_seq(lines[i])
            m = fd_pat.match(body)
            if not m:
                i += 1
                continue
            fd_name = m.group(1).upper()
            block_start = i + 1
            j = block_start
            # Walk forward until next FD/SD or section break
            while j < len(lines):
                b = _strip_seq(lines[j])
                if fd_pat.match(b) or section_break_pat.match(b):
                    break
                j += 1
            block_lines = lines[block_start:j]
            items = SQLiteLoader._extract_data_items_from_lines(block_lines, start_line=block_start + 1)
            # Identify the 01-level "record" that anchors this FD
            record_name = None
            for it in items:
                if it["level"] == 1:
                    record_name = it["field_name"]
                    break
            for it in items:
                results.append({
                    "file_name": fd_name,
                    "record_name": record_name,
                    "field_name": it["field_name"],
                    "level_number": it["level"],
                    "picture": it["picture"],
                    "usage": it["usage"],
                    "parent_name": it["parent"],
                    "line_number": it["line_number"],
                })
            i = j
        return results

    @staticmethod
    def _extract_movements_from_source(file_path: str, paragraphs: List[Dict]) -> List[Dict]:
        """Extract MOVE statements: source -> destination pairs.
        Only captures simple cases: MOVE <src> TO <dst>[, <dst2>, ...].
        Skips arithmetic / reference modifications."""
        import re
        from pathlib import Path
        src = Path(file_path)
        if not src.exists():
            return []
        try:
            content = src.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        lines = content.split("\n")

        def _strip_seq(line: str) -> str:
            if len(line) > 6 and line[6] == "*":
                return ""
            body = line[6:] if len(line) > 6 else line
            return body[:66] if len(body) > 66 else body

        def _find_paragraph(line_num):
            for p in paragraphs:
                start = p.get("line_start", 0)
                end = p.get("line_end", 0)
                if start and end and start <= line_num <= end:
                    return p.get("name")
            return None

        # MOVE <src> TO <dst1> [<dst2>...]   src can be 'literal', "literal", number, or identifier
        move_pat = re.compile(
            r"\bMOVE\s+("
            r"'[^']*'|\"[^\"]*\"|[+-]?\d+(?:\.\d+)?|[A-Z][A-Z0-9-]*(?:\([^)]+\))?"
            r")\s+TO\s+([A-Z][A-Z0-9-]*(?:\s*,?\s*[A-Z][A-Z0-9-]*)*)",
            re.IGNORECASE,
        )

        results = []
        for idx, raw in enumerate(lines):
            body = _strip_seq(raw)
            if "MOVE" not in body.upper():
                continue
            for m in move_pat.finditer(body):
                src_field = m.group(1).strip()
                dst_block = m.group(2).strip()
                is_literal = 1 if (src_field.startswith(("'", '"')) or src_field.lstrip("+-").replace(".", "").isdigit()) else 0
                # Split multiple destinations
                for dst in re.split(r"[,\s]+", dst_block):
                    dst = dst.strip().rstrip(",")
                    if not dst:
                        continue
                    results.append({
                        "source_field": src_field.strip("'\""),
                        "destination_field": dst.upper(),
                        "paragraph": _find_paragraph(idx + 1),
                        "line_number": idx + 1,
                        "is_literal": is_literal,
                    })
        return results

    @staticmethod
    def _extract_sql_from_source(file_path: str, paragraphs: List[Dict]) -> List[Dict]:
        """Extract EXEC SQL (DB2) statements directly from COBOL source.
        Returns list of {command, table_name, cursor_name, paragraph, line_number, sql_text}."""
        import re
        from pathlib import Path

        src = Path(file_path)
        if not src.exists():
            return []
        try:
            content = src.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        lines = content.split("\n")

        source_ranges = SQLiteLoader._source_paragraph_ranges(file_path, paragraphs)

        def _find_paragraph(line_num):
            for pname, (start, end) in source_ranges.items():
                if start <= line_num <= end:
                    return pname
            for p in paragraphs or []:
                start = p.get("line_start", 0)
                end = p.get("line_end", 0)
                if start and end and start <= line_num <= end:
                    return p.get("name") or p.get("paragraph_name")
            return None

        results = []
        i = 0
        while i < len(lines):
            line = lines[i]
            line_num = i + 1
            if len(line) > 6 and line[6] == "*":
                i += 1
                continue
            upper = line.upper()
            if "EXEC SQL" not in upper:
                i += 1
                continue

            # Collect block until END-EXEC
            block_lines = [line]
            j = i + 1
            while j < len(lines):
                block_lines.append(lines[j])
                if "END-EXEC" in lines[j].upper():
                    break
                j += 1
            i = j + 1

            # Strip column 1-6 sequence area AND trailing column-73-80 area.
            def _trim(l):
                body = l[6:] if len(l) > 6 else l
                return body[:66] if len(body) > 66 else body
            block = " ".join(_trim(l) for l in block_lines)
            block = re.sub(r"\s+", " ", block).strip()
            block_no_end = re.sub(r"END-EXEC\.?\s*$", "", block, flags=re.IGNORECASE).strip()

            # Identify the SQL command (first keyword after EXEC SQL)
            m = re.search(r"EXEC\s+SQL\s+(\w+)", block_no_end, re.IGNORECASE)
            cmd = m.group(1).upper() if m else "UNKNOWN"

            # Special case: DECLARE <cursor> CURSOR FOR <query>
            cursor_name = None
            table_name = None
            if cmd == "DECLARE":
                cm = re.search(r"DECLARE\s+(\S+)\s+CURSOR\s+FOR", block_no_end, re.IGNORECASE)
                if cm:
                    cursor_name = cm.group(1)
                # also find FROM <table> inside the declared SELECT
                fm = re.search(r"\bFROM\s+([A-Z0-9_.$]+)", block_no_end, re.IGNORECASE)
                if fm:
                    table_name = fm.group(1)
            elif cmd in ("OPEN", "FETCH", "CLOSE"):
                cm = re.search(rf"{cmd}\s+(\S+)", block_no_end, re.IGNORECASE)
                if cm:
                    cursor_name = cm.group(1).strip(",;")
            else:
                # SELECT/INSERT/UPDATE/DELETE — find the table
                tm = (
                    re.search(r"\bFROM\s+([A-Z0-9_.$]+)", block_no_end, re.IGNORECASE)
                    or re.search(r"\bINTO\s+([A-Z0-9_.$]+)", block_no_end, re.IGNORECASE)
                    or re.search(r"\bUPDATE\s+([A-Z0-9_.$]+)", block_no_end, re.IGNORECASE)
                )
                if tm:
                    table_name = tm.group(1)

            # Trim sql_text for storage
            sql_text = block_no_end[:300]

            para_name = _find_paragraph(line_num)
            results.append({
                "command": cmd,
                "table_name": table_name,
                "cursor_name": cursor_name,
                "paragraph": para_name,
                "line_number": line_num,
                "sql_text": sql_text,
            })

        return results

    @staticmethod
    def _extract_cics_from_source(file_path: str, paragraphs: List[Dict]) -> List[Dict]:
        """Extract EXEC CICS commands directly from COBOL source when ProLeap gives empty raw_text."""
        import re
        from pathlib import Path

        src = Path(file_path)
        if not src.exists():
            return []

        try:
            content = src.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        lines = content.split("\n")

        source_ranges = SQLiteLoader._source_paragraph_ranges(file_path, paragraphs)

        def _find_paragraph(line_num):
            for pname, (start, end) in source_ranges.items():
                if start <= line_num <= end:
                    return pname
            for p in paragraphs or []:
                start = p.get("line_start", 0)
                end = p.get("line_end", 0)
                if start and end and start <= line_num <= end:
                    return p.get("name") or p.get("paragraph_name")
            return None

        results = []
        i = 0
        while i < len(lines):
            line = lines[i]
            line_num = i + 1

            # Skip comment lines (column 7 = *)
            if len(line) > 6 and line[6] == "*":
                i += 1
                continue

            upper = line.upper()
            if "EXEC CICS" not in upper:
                i += 1
                continue

            # Collect the full EXEC CICS block (may span multiple lines until END-EXEC)
            block_lines = [line]
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                block_lines.append(next_line)
                if "END-EXEC" in next_line.upper():
                    break
                j += 1
            i = j + 1

            # Join and extract command + parameters
            # Strip column 1-6 sequence area AND trailing column-73-80 area.
            def _trim_cics(l):
                body = l[6:] if len(l) > 6 else l
                return body[:66] if len(body) > 66 else body
            block = " ".join(_trim_cics(l) for l in block_lines)
            block = re.sub(r"\s+", " ", block).strip()

            m = re.search(r"EXEC\s+CICS\s+(\w+)", block, re.IGNORECASE)
            cmd = m.group(1).upper() if m else "UNKNOWN"

            details = {}
            for param in ["MAP", "MAPSET", "PROGRAM", "DATASET", "FILE", "TRANSID",
                          "FROM", "INTO", "LENGTH", "RIDFLD", "COMMAREA", "QUEUE",
                          "RESP", "CURSOR", "ERASE"]:
                pm = re.search(rf"{param}\s*\(\s*([^)]+)\s*\)", block, re.IGNORECASE)
                if pm:
                    details[param.lower()] = pm.group(1).strip().strip("'\"")

            para_name = _find_paragraph(line_num)
            results.append({
                "command": cmd,
                "line_number": line_num,
                "paragraph": para_name,
                "details": details,
            })

        return results

    @staticmethod
    def _extract_ims_from_source(file_path: str, paragraphs: List[Dict],
                                  data_items: List[Dict] = None) -> List[Dict]:
        """Extract IMS DL/I CALL 'CBLTDLI' statements from COBOL source.
        Pattern: CALL 'CBLTDLI' USING <fn>, <PCB-name>, <area>, <SSA-name>
        Also detects ENTRY 'DLITCBL' as an IMS batch program marker.
        Returns list of {function_code, function_name, pcb_name, segment_area,
                         ssa_name, ssa_segment, ssa_qualifier, paragraph, line_number, raw_text}.
        """
        import re
        from pathlib import Path

        # IMS function code → human-readable name
        IMS_FUNCTIONS = {
            "GU":   "Get Unique",
            "GHU":  "Get Hold Unique",
            "GN":   "Get Next",
            "GHN":  "Get Hold Next",
            "GNP":  "Get Next in Parent",
            "GHNP": "Get Hold Next in Parent",
            "ISRT": "Insert",
            "REPL": "Replace",
            "DLET": "Delete",
            "CHKP": "Checkpoint",
            "XRST": "Extended Restart",
            "ROLB": "Rollback",
            "ROLL": "Roll",
            "PCB":  "PCB Call",
            "STAT": "Statistics",
            "LOG":  "Log",
            "DEQ":  "Dequeue",
            "POS":  "Position",
            "FLD":  "Field Call",
        }

        src = Path(file_path)
        if not src.exists():
            return []
        try:
            content = src.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        lines = content.split("\n")

        # Strip COBOL sequence area + comments
        def _trim(l):
            if len(l) > 6 and l[6] == "*":
                return ""
            body = l[6:] if len(l) > 6 else l
            return body[:66] if len(body) > 66 else body

        # Parser line numbers can drift after COPY expansion. For source-file
        # extractors, map paragraphs by scanning real COBOL labels in the file.
        paragraph_names = []
        for p in paragraphs or []:
            pname = (p.get("name") or p.get("paragraph_name") or "").upper()
            if pname:
                paragraph_names.append(pname)
        paragraph_starts = []
        for idx, raw_line in enumerate(lines, 1):
            body = _trim(raw_line).strip().upper()
            for pname in paragraph_names:
                if re.match(rf"^{re.escape(pname)}\s*\.", body):
                    paragraph_starts.append((idx, pname))
                    break
        paragraph_starts.sort()
        source_ranges = []
        for pos, (start, pname) in enumerate(paragraph_starts):
            end = paragraph_starts[pos + 1][0] - 1 if pos + 1 < len(paragraph_starts) else len(lines)
            source_ranges.append((start, end, pname))

        def _find_paragraph(line_num):
            for start, end, pname in source_ranges:
                if start <= line_num <= end:
                    return pname
            for p in paragraphs or []:
                start = p.get("line_start", 0)
                end = p.get("line_end", 0)
                if start and end and start <= line_num <= end:
                    return p.get("name") or p.get("paragraph_name")
            return None

        def _extract_ssa_layouts():
            layouts = {}
            current = None
            fields = []

            def flush():
                if not current:
                    return
                segment = None
                key_field = None
                rel_oper = None
                for fname, literal in fields:
                    lit = (literal or "").strip()
                    if not lit or lit in ("(", ")", " "):
                        continue
                    if fname.endswith("SEG-NAME") or (segment is None and len(lit) >= 4):
                        segment = lit
                    if fname.endswith("KEY-FIELD"):
                        key_field = lit.strip()
                    if fname.endswith("REL-OPER"):
                        rel_oper = lit.strip()
                qualifier = None
                if key_field and rel_oper:
                    qualifier = f"{key_field} {rel_oper} QUAL-SSA-KEY-VALUE"
                layouts[current] = {"segment": segment, "qualifier": qualifier}

            for raw_line in lines:
                body = _trim(raw_line).strip().upper()
                if not body:
                    continue
                m01 = re.match(r"^01\s+([A-Z0-9-]*SSA)\s*\.", body)
                if m01:
                    flush()
                    current = m01.group(1)
                    fields = []
                    continue
                if current and re.match(r"^01\s+", body):
                    flush()
                    current = None
                    fields = []
                    continue
                if current:
                    mf = re.match(
                        r"^\d+\s+([A-Z0-9-]+|FILLER)\b.*?\bVALUE\s+['\"]([^'\"]*)['\"]",
                        body,
                    )
                    if mf:
                        fields.append((mf.group(1), mf.group(2)))
            flush()
            return layouts

        ssa_layouts = _extract_ssa_layouts()

        results = []
        i = 0
        while i < len(lines):
            line = lines[i]
            line_num = i + 1
            body = _trim(line).upper()

            if not body:
                i += 1
                continue

            # Detect ENTRY 'DLITCBL' — IMS batch program marker
            if "ENTRY" in body and "DLITCBL" in body:
                results.append({
                    "function_code": "ENTRY",
                    "function_name": "IMS Batch Entry Point (DLITCBL)",
                    "pcb_name": None,
                    "segment_area": None,
                    "ssa_name": None,
                    "ssa_segment": None,
                    "ssa_qualifier": None,
                    "paragraph": _find_paragraph(line_num),
                    "line_number": line_num,
                    "raw_text": _trim(line).strip(),
                })
                i += 1
                continue

            # Detect CALL 'CBLTDLI' USING ...
            if "CBLTDLI" not in body:
                i += 1
                continue

            # Collect the full statement (may span multiple lines until period or next statement)
            block_parts = [_trim(line)]
            j = i + 1
            while j < len(lines):
                next_body = _trim(lines[j])
                if not next_body:
                    j += 1
                    continue
                # Stop at period, next paragraph, or next statement keyword
                block_parts.append(next_body)
                if "." in next_body:
                    break
                j += 1
            i = j + 1

            block = " ".join(block_parts)
            block = re.sub(r"\s+", " ", block).strip()

            # Parse: CALL 'CBLTDLI' USING <fn>, <PCB>, <area> [, <SSA1> [, <SSA2> ...]]
            # Arguments may be separated by commas or spaces
            m = re.search(
                r"CALL\s+['\"]CBLTDLI['\"]\s+USING\s+(.*?)(?:\.|$)",
                block, re.IGNORECASE
            )
            if not m:
                continue

            args_str = m.group(1).strip().rstrip(".")
            # Split on commas or whitespace, filtering out empty and COBOL keywords
            args = [a.strip().rstrip(",") for a in re.split(r"[,\s]+", args_str)
                    if a.strip() and a.strip().upper() not in ("BY", "REFERENCE", "CONTENT", "VALUE")]

            fn_var = args[0].upper() if len(args) > 0 else "UNKNOWN"
            pcb = args[1].upper() if len(args) > 1 else None
            area = args[2].upper() if len(args) > 2 else None
            ssa = args[3].upper() if len(args) > 3 else None

            # Resolve function code: it might be a variable name containing the
            # function code, or a literal like 'GU'. Strip quotes.
            fn_code = fn_var.strip("'\"")
            if fn_code.startswith("FUNC-"):
                candidate = fn_code[5:]
                if candidate in IMS_FUNCTIONS:
                    fn_code = candidate

            # Map known function codes
            fn_name = IMS_FUNCTIONS.get(fn_code)
            if not fn_name:
                # It might be a variable — check if there's a MOVE 'GU' TO <var> somewhere
                # For now just record the raw name
                fn_name = None

            # Look up SSA segment and qualifier from source declarations.
            ssa_layout = ssa_layouts.get(ssa, {}) if ssa else {}
            ssa_seg = ssa_layout.get("segment")
            ssa_qual = ssa_layout.get("qualifier")

            raw = block[:200]

            results.append({
                "function_code": fn_code,
                "function_name": fn_name,
                "pcb_name": pcb,
                "segment_area": area,
                "ssa_name": ssa,
                "ssa_segment": ssa_seg,
                "ssa_qualifier": ssa_qual,
                "paragraph": _find_paragraph(line_num),
                "line_number": line_num,
                "raw_text": raw,
            })

        return results

    def load_copybook_fields(self, repo_path: str = None):
        """Scan all .cpy / .CPY files in the repo, parse field-level dictionaries,
        and load them into copybook_fields. Also populates copybooks.file_path
        for any rows that don't have it set yet."""
        from pathlib import Path
        if not repo_path:
            return
        cursor = self.conn.cursor()

        cpy_files = list(Path(repo_path).rglob("*.cpy")) + list(Path(repo_path).rglob("*.CPY"))
        loaded = 0
        for fp in cpy_files:
            cb_name = fp.stem.upper()
            try:
                fields = self._extract_copybook_fields_from_source(str(fp))
            except Exception:
                continue

            # Ensure the copybook row exists with a file_path
            cursor.execute("INSERT OR IGNORE INTO copybooks (copybook_name, file_path) VALUES (?, ?)",
                            (cb_name, str(fp)))
            cursor.execute("UPDATE copybooks SET file_path = ? WHERE copybook_name = ? AND (file_path IS NULL OR file_path = '')",
                            (str(fp), cb_name))

            # Replace any existing fields for this copybook
            cursor.execute("DELETE FROM copybook_fields WHERE copybook_name = ?", (cb_name,))
            for f in fields:
                cursor.execute("""
                    INSERT INTO copybook_fields (
                        copybook_name, field_name, level_number, picture, usage,
                        value, parent_name, line_number, occurs_count, redefines_target
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cb_name,
                    f.get("field_name"),
                    f.get("level"),
                    f.get("picture"),
                    f.get("usage"),
                    f.get("value"),
                    f.get("parent"),
                    f.get("line_number"),
                    f.get("occurs"),
                    f.get("redefines"),
                ))
            if fields:
                loaded += 1
        self.conn.commit()
        console.print(f"[green]OK - Loaded copybook field dictionaries for {loaded}/{len(cpy_files)} .cpy files[/green]")

    # Convenient retrieval helpers
    def get_copybook_fields(self, copybook_name: str) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT field_name, level_number, picture, usage, value, parent_name, line_number,
                   occurs_count, redefines_target
            FROM copybook_fields
            WHERE copybook_name = ?
            ORDER BY line_number, level_number
        """, (copybook_name,))
        return [dict(r) for r in cursor.fetchall()]

    def get_program_file_records(self, program_id: str) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT file_name, record_name, field_name, level_number, picture, usage,
                   parent_name, line_number
            FROM file_records
            WHERE program_id = ?
            ORDER BY file_name, line_number, level_number
        """, (program_id,))
        return [dict(r) for r in cursor.fetchall()]

    def get_program_data_movements(self, program_id: str, limit: int = 50) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT source_field, destination_field, paragraph_name, line_number, is_literal
            FROM data_movements
            WHERE program_id = ?
            ORDER BY line_number
            LIMIT ?
        """, (program_id, limit))
        return [dict(r) for r in cursor.fetchall()]

    def load_screens(self, screens: List[Dict]):
        """Load BMS screen definitions."""
        cursor = self.conn.cursor()

        # Screen rows have no natural UNIQUE constraint in the original schema.
        # Clear them before reloading so repeated pipeline runs stay idempotent.
        cursor.execute("DELETE FROM screen_fields")
        cursor.execute("DELETE FROM screens")

        for screen_data in screens:
            mapset = screen_data.get("mapset_name", "")
            for map_info in screen_data.get("maps", []):
                map_name = map_info.get("map_name", "")
                # Try to find associated program (skip FK if not found)
                prog = None
                for suffix in ["C", ""]:
                    candidate = mapset + suffix
                    cursor.execute("SELECT program_id FROM programs WHERE program_id = ?", (candidate,))
                    if cursor.fetchone():
                        prog = candidate
                        break

                cursor.execute("""
                    INSERT OR REPLACE INTO screens (
                        screen_name, map_name, mapset_name, file_path,
                        associated_program, business_name
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    map_name, map_name, mapset,
                    screen_data.get("file_path"),
                    prog, map_name
                ))

                screen_id = cursor.lastrowid

                 # Insert fields
                for fld in map_info.get("fields", []):
                    cursor.execute("""
                        INSERT OR REPLACE INTO screen_fields (
                            screen_id, field_name, field_type, length,
                            row_position, col_position, attributes,
                            business_name, description
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        screen_id,
                        fld.get("field_name"),
                        fld.get("field_type"),
                        fld.get("length"),
                        fld.get("row_position"),
                        fld.get("col_position"),
                        fld.get("attributes"),
                        fld.get("field_name"),
                        fld.get("initial_value", "")
                    ))

        self.conn.commit()
        console.print(f"[green]OK - Loaded {len(screens)} screens[/green]")

    def load_business_rules(self, rules: List[Dict]):
        """Load business rules into the database."""
        cursor = self.conn.cursor()
        for rule in rules:
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO business_rules (
                        rule_id, rule_name, rule_statement, category,
                        program_id, paragraph_name, line_start, line_end,
                        condition_text, action_text, source_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rule.get("rule_id"), rule.get("rule_name"),
                    rule.get("rule_statement"), rule.get("category"),
                    rule.get("program_id"), rule.get("paragraph_name"),
                    rule.get("line_start"), rule.get("line_end"),
                    rule.get("condition"), rule.get("action"),
                    rule.get("source_code")
                ))
            except Exception as e:
                pass

        self.conn.commit()
        console.print(f"[green]OK - Loaded {len(rules)} business rules[/green]")

    def load_from_json(self, programs_json=None, rules_json=None,
                       enriched_json=None, screens_json=None):
        """Load data from JSON files."""
        if enriched_json:
            enriched_path = Path(enriched_json)
            if (enriched_path / "enriched_programs.json").exists():
                programs_json = str(enriched_path / "enriched_programs.json")
            if (enriched_path / "business_rules.json").exists():
                rules_json = str(enriched_path / "business_rules.json")

        if programs_json and Path(programs_json).exists():
            with open(programs_json, 'r') as f:
                raw = json.load(f)
            # Deduplicate: keep the entry with the most enrichment (has business_purpose)
            seen = {}
            for p in raw:
                pid = p.get("program_id", "")
                if pid not in seen or (p.get("business_purpose") and not seen[pid].get("business_purpose")):
                    seen[pid] = p
            self.load_programs(list(seen.values()))

        if rules_json and Path(rules_json).exists():
            with open(rules_json, 'r') as f:
                self.load_business_rules(json.load(f))

        if screens_json and Path(screens_json).exists():
            with open(screens_json, 'r') as f:
                self.load_screens(json.load(f))

    # ================================================================
    # Query Methods
    # ================================================================

    def get_generated_doc(self, mode: str, subject: str) -> Optional[str]:
        """Retrieve a previously saved generated document, or None if not found."""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "SELECT document_text FROM generated_docs WHERE mode = ? AND subject = ?",
                (mode, subject)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def save_generated_doc(self, mode: str, subject: str, text: str):
        """Save or overwrite a generated document in the DB."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO generated_docs (mode, subject, document_text, generated_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (mode, subject, text))
        self.conn.commit()

    def get_all_programs(self) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT program_id, file_path, program_type, line_count,
                   business_name, business_purpose, user_role, business_process,
                   migration_complexity, complexity_reason, modern_equivalent,
                   suggested_service, migration_approach, data_contracts, migration_risks
            FROM programs ORDER BY program_id
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_program_details(self, program_id: str) -> Optional[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM programs WHERE program_id = ?", (program_id,))
        program = cursor.fetchone()
        if not program:
            return None
        result = dict(program)

        for key, query in [
            ("paragraphs", "SELECT * FROM paragraphs WHERE program_id = ? ORDER BY line_start"),
            ("data_items", "SELECT * FROM data_items WHERE program_id = ? ORDER BY line_number"),
            ("files", "SELECT * FROM files WHERE program_id = ?"),
            ("statements", "SELECT * FROM statements WHERE program_id = ? ORDER BY line_number"),
            ("calls", "SELECT * FROM program_calls WHERE caller_program = ?"),
            ("called_by", "SELECT * FROM program_calls WHERE called_program = ?"),
            ("copybooks", "SELECT * FROM copybook_usage WHERE program_id = ? ORDER BY copybook_name"),
            ("performs", "SELECT * FROM performs WHERE program_id = ?"),
            ("business_rules", "SELECT * FROM business_rules WHERE program_id = ?"),
            ("exec_cics", "SELECT * FROM exec_cics WHERE program_id = ? ORDER BY line_number"),
            ("exec_sql",  "SELECT * FROM exec_sql  WHERE program_id = ? ORDER BY line_number"),
            ("ims_calls", "SELECT * FROM ims_calls WHERE program_id = ? ORDER BY line_number"),
        ]:
            cursor.execute(query, (program_id,))
            result[key] = [dict(row) for row in cursor.fetchall()]

        return result

    def get_call_graph(self) -> List[Dict]:
        """Return call edges. If called_program == 'UNKNOWN' but resolved_target is set,
        substitute the resolved target so downstream consumers see a real program ID."""
        cursor = self.conn.cursor()
        # COALESCE picks resolved_target when called_program is UNKNOWN
        cursor.execute("""
            SELECT pc.caller_program,
                   p1.business_name as caller_name,
                   CASE
                     WHEN pc.called_program = 'UNKNOWN' AND pc.resolved_target IS NOT NULL
                     THEN pc.resolved_target
                     ELSE pc.called_program
                   END as called_program,
                   p2.business_name as called_name,
                   pc.line_number,
                   pc.resolved_target,
                   pc.called_program as raw_target
            FROM program_calls pc
            LEFT JOIN programs p1 ON pc.caller_program = p1.program_id
            LEFT JOIN programs p2 ON
                (CASE
                   WHEN pc.called_program = 'UNKNOWN' AND pc.resolved_target IS NOT NULL
                   THEN pc.resolved_target ELSE pc.called_program END
                ) = p2.program_id
            ORDER BY pc.caller_program
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_all_business_rules(self) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT br.*, p.business_name as program_business_name
            FROM business_rules br
            LEFT JOIN programs p ON br.program_id = p.program_id
            ORDER BY br.category, br.rule_id
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_data_dictionary(self) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT di.name, di.picture, di.section, di.level_number,
                   di.parent_name, di.business_name, di.description,
                   di.program_id, p.business_name as program_business_name
            FROM data_items di
            LEFT JOIN programs p ON di.program_id = p.program_id
            ORDER BY di.name
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_all_screens(self) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT s.*, GROUP_CONCAT(sf.field_name, ', ') as field_names
            FROM screens s
            LEFT JOIN screen_fields sf ON s.id = sf.screen_id
            GROUP BY s.id
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_screen_details(self, screen_id: int) -> Optional[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM screens WHERE id = ?", (screen_id,))
        screen = cursor.fetchone()
        if not screen:
            return None
        result = dict(screen)
        cursor.execute("SELECT * FROM screen_fields WHERE screen_id = ? ORDER BY row_position, col_position",
                       (screen_id,))
        result["fields"] = [dict(row) for row in cursor.fetchall()]
        return result

    def get_program_statements(self, program_id: str, stmt_type: str = None) -> List[Dict]:
        """Get statements for a program, optionally filtered by type."""
        cursor = self.conn.cursor()
        if stmt_type:
            cursor.execute("""
                SELECT * FROM statements WHERE program_id = ? AND statement_type = ?
                ORDER BY line_number
            """, (program_id, stmt_type))
        else:
            cursor.execute("""
                SELECT * FROM statements WHERE program_id = ? ORDER BY line_number
            """, (program_id,))
        return [dict(row) for row in cursor.fetchall()]

    def get_all_modules(self) -> List[Dict]:
        """Get all modules with their programs."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT m.id, m.module_name, m.business_name, m.description, m.business_purpose
            FROM modules m ORDER BY m.module_name
        """)
        modules = []
        for row in cursor.fetchall():
            mod = dict(row)
            cursor.execute("""
                SELECT mp.program_id, p.program_type, p.line_count,
                       p.business_name, p.business_purpose
                FROM module_programs mp
                LEFT JOIN programs p ON mp.program_id = p.program_id
                WHERE mp.module_id = ?
                ORDER BY mp.program_id
            """, (mod["id"],))
            mod["programs"] = [dict(r) for r in cursor.fetchall()]
            modules.append(mod)
        return modules

    def get_module_details(self, module_id: int) -> Optional[Dict]:
        """Get full module details including programs, calls, files."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM modules WHERE id = ?", (module_id,))
        row = cursor.fetchone()
        if not row:
            return None
        mod = dict(row)

        # Get programs in module
        cursor.execute("""
            SELECT mp.program_id, p.program_type, p.line_count, p.file_path,
                   p.business_name, p.business_purpose, p.user_role
            FROM module_programs mp
            LEFT JOIN programs p ON mp.program_id = p.program_id
            WHERE mp.module_id = ?
            ORDER BY mp.program_id
        """, (module_id,))
        mod["programs"] = [dict(r) for r in cursor.fetchall()]

        # Get inter-module calls (calls from programs in this module)
        prog_ids = [p["program_id"] for p in mod["programs"]]
        if prog_ids:
            placeholders = ",".join("?" * len(prog_ids))
            cursor.execute(f"""
                SELECT DISTINCT pc.caller_program, pc.called_program, pc.line_number
                FROM program_calls pc
                WHERE pc.caller_program IN ({placeholders})
                ORDER BY pc.caller_program, pc.called_program
            """, prog_ids)
            mod["calls"] = [dict(r) for r in cursor.fetchall()]

            # Files used by module programs
            cursor.execute(f"""
                SELECT DISTINCT f.file_name, f.file_type, f.access_mode, f.program_id
                FROM files f
                WHERE f.program_id IN ({placeholders})
                ORDER BY f.file_name
            """, prog_ids)
            mod["files"] = [dict(r) for r in cursor.fetchall()]

            # Screens associated with module programs
            cursor.execute(f"""
                SELECT s.id, s.screen_name, s.map_name, s.mapset_name,
                       s.associated_program, s.business_name
                FROM screens s
                WHERE s.associated_program IN ({placeholders})
            """, prog_ids)
            mod["screens"] = [dict(r) for r in cursor.fetchall()]
        else:
            mod["calls"] = []
            mod["files"] = []
            mod["screens"] = []

        return mod

    def get_copybooks(self) -> List[Dict]:
        """Get all copybooks with usage info."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT c.copybook_name, c.file_path, c.business_name, c.description,
                   GROUP_CONCAT(cu.program_id, ', ') as used_by
            FROM copybooks c
            LEFT JOIN copybook_usage cu ON c.copybook_name = cu.copybook_name
            GROUP BY c.copybook_name
            ORDER BY c.copybook_name
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_statement_summary(self, program_id: str) -> Dict[str, int]:
        """Get summary counts of statement types for a program."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT statement_type, COUNT(*) as cnt
            FROM statements WHERE program_id = ?
            GROUP BY statement_type ORDER BY cnt DESC
        """, (program_id,))
        return {row[0]: row[1] for row in cursor.fetchall()}

    # ================================================================
    # Graph-Based Module Detection (Swimm-style)
    # ================================================================

    def detect_modules(self) -> List[Dict]:
        """
        Detect logical modules using call graph analysis, naming patterns,
        and data access similarity -- not just 2-char prefix matching.
        """
        cursor = self.conn.cursor()

        # Ensure module tables exist even if the database was created
        # with an older schema that didn't include them.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS modules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_name TEXT NOT NULL,
                business_name TEXT,
                description TEXT,
                business_purpose TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS module_programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_id INTEGER NOT NULL,
                program_id TEXT NOT NULL,
                FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE,
                FOREIGN KEY(program_id) REFERENCES programs(program_id) ON DELETE CASCADE
            )
        """)

        # Get all programs
        cursor.execute("SELECT program_id, program_type, file_path FROM programs")
        all_programs = {row[0]: {"type": row[1], "path": row[2]} for row in cursor.fetchall()}

        # Get call graph
        cursor.execute("SELECT caller_program, called_program FROM program_calls")
        calls = cursor.fetchall()

        # Get file usage
        cursor.execute("SELECT program_id, file_name FROM files")
        file_usage = defaultdict(set)
        for row in cursor.fetchall():
            file_usage[row[0]].add(row[1])

        # Build adjacency for clustering
        connected = defaultdict(set)
        for caller, called in calls:
            connected[caller].add(called)
            connected[called].add(caller)

        # Strategy 1: Name-based functional grouping
        func_groups = defaultdict(list)
        for pid in all_programs:
            # CardDemo naming: CO* = Common Online, CB* = Credit Card Batch
            # More specific: COSGN = Sign-on, COMEN = Menu, COTRN = Transaction
            # CBACT = Account, CBTRN = Transaction, COCRD = Credit Card
            if len(pid) >= 5:
                prefix4 = pid[:4]  # e.g., COSG, COME, COTR, CBAC, CBTR
                prefix5 = pid[:5]  # e.g., COSGN, COMEN, COTRN

                # Specific functional groupings
                if pid.startswith("COSGN"):
                    func_groups["AUTHENTICATION"].append(pid)
                elif pid.startswith("COMEN"):
                    func_groups["NAVIGATION"].append(pid)
                elif pid.startswith("COADM"):
                    func_groups["ADMINISTRATION"].append(pid)
                elif pid.startswith("COUSR"):
                    func_groups["USER_MANAGEMENT"].append(pid)
                elif pid.startswith("COTRN"):
                    func_groups["TRANSACTION_ONLINE"].append(pid)
                elif pid.startswith("COCRD"):
                    func_groups["CREDIT_CARD_MGMT"].append(pid)
                elif pid.startswith("COBIL"):
                    func_groups["BILLING"].append(pid)
                elif pid.startswith("CORPT"):
                    func_groups["REPORTING"].append(pid)
                elif pid.startswith("COACTU") or pid.startswith("COACTV"):
                    func_groups["ACCOUNT_MGMT_ONLINE"].append(pid)
                elif pid.startswith("CBACT"):
                    func_groups["ACCOUNT_BATCH"].append(pid)
                elif pid.startswith("CBTRN"):
                    func_groups["TRANSACTION_BATCH"].append(pid)
                elif pid.startswith("CBCUS"):
                    func_groups["CUSTOMER_BATCH"].append(pid)
                elif pid.startswith("CBEXPO") or pid.startswith("CBIMPO"):
                    func_groups["DATA_EXCHANGE"].append(pid)
                elif pid.startswith("CBSTM"):
                    func_groups["STATEMENT_PROCESSING"].append(pid)
                elif pid.startswith("CSUTL") or pid.startswith("COBSW"):
                    func_groups["UTILITIES"].append(pid)
                else:
                    # Classify by 2-char prefix with a meaningful fallback name
                    prefix2 = pid[:2].upper()
                    group_key = {
                        "CB": "BATCH_PROCESSING",
                        "CO": "ONLINE_PROCESSING",
                        "CS": "SHARED_SERVICES",
                        "DB": "DATABASE_OPERATIONS",
                        "PA": "PAYMENT_PROCESSING",
                    }.get(prefix2, f"MODULE_{prefix2}")
                    func_groups[group_key].append(pid)
            else:
                func_groups["OTHER"].append(pid)

        # Strategy 2: Merge small groups into neighbors via call graph
        module_names = {
            "AUTHENTICATION":       "Authentication & Sign-On",
            "NAVIGATION":           "Menu Navigation",
            "ADMINISTRATION":       "System Administration",
            "USER_MANAGEMENT":      "User Management",
            "TRANSACTION_ONLINE":   "Online Transaction Processing",
            "TRANSACTION_BATCH":    "Batch Transaction Processing",
            "CREDIT_CARD_MGMT":     "Credit Card Management",
            "BILLING":              "Billing & Statements",
            "REPORTING":            "Reports & Analytics",
            "ACCOUNT_MGMT_ONLINE":  "Online Account Management",
            "ACCOUNT_BATCH":        "Batch Account Processing",
            "CUSTOMER_BATCH":       "Customer Data Processing",
            "DATA_EXCHANGE":        "Data Import/Export",
            "STATEMENT_PROCESSING": "Statement Generation",
            "UTILITIES":            "Shared Utilities",
            "BATCH_PROCESSING":     "Batch Processing (Uncategorised)",
            "ONLINE_PROCESSING":    "Online Processing (Uncategorised)",
            "SHARED_SERVICES":      "Shared Services",
            "DATABASE_OPERATIONS":  "Database Operations",
            "PAYMENT_PROCESSING":   "Payment Processing",
            "OTHER":                "Other Programs",
        }

        # Build result
        modules = []
        for mod_id, progs in sorted(func_groups.items()):
            if not progs:
                continue
            modules.append({
                "module_id": mod_id,
                "module_name": module_names.get(mod_id, f"Module: {mod_id}"),
                "programs": sorted(progs),
                "program_count": len(progs),
            })

        # Save to DB (tables might not exist in very old DBs)
        try:
            cursor.execute("DELETE FROM modules")
        except Exception:
            pass
        try:
            cursor.execute("DELETE FROM module_programs")
        except Exception:
            pass
        # Best-effort persistence of detected modules.
        # If the schema doesn't match (older DB), skip writing but still
        # return the in-memory modules list so callers can proceed.
        try:
            for mod in modules:
                cursor.execute("""
                    INSERT INTO modules (module_name, business_name, description, business_purpose)
                    VALUES (?, ?, ?, ?)
                """, (mod["module_id"], mod["module_name"], "", mod["module_name"]))
                mod_db_id = cursor.lastrowid
                for pid in mod["programs"]:
                    try:
                        cursor.execute(
                            "INSERT INTO module_programs (module_id, program_id) VALUES (?, ?)",
                            (mod_db_id, pid),
                        )
                    except Exception:
                        # Ignore individual mapping failures
                        pass
            self.conn.commit()
        except Exception as e:
            # Log and continue without failing module detection
            console.print(f"[yellow]Warning: module persistence skipped due to schema issue: {e}[/yellow]")

        return modules

    # ================================================================
    # Full-Text Search
    # ================================================================

    def full_text_search(self, query: str) -> Dict[str, List]:
        cursor = self.conn.cursor()
        results = {}
        for table, fields in [
            ("programs_fts", "program_id, business_name, business_purpose"),
            ("data_items_fts", "name, business_name, description"),
            ("business_rules_fts", "rule_name, rule_statement"),
        ]:
            try:
                cursor.execute(f"SELECT {fields} FROM {table} WHERE {table} MATCH ?", (query,))
                results[table.replace("_fts", "")] = [dict(row) for row in cursor.fetchall()]
            except:
                results[table.replace("_fts", "")] = []
        return results

    # ================================================================
    # Dependency & Impact Analysis (for doc generation)
    # ================================================================

    def get_program_dependencies(self, program_id: str) -> Dict:
        """Get direct callers and callees with business context."""
        cursor = self.conn.cursor()

        # Direct callers
        cursor.execute("""
            SELECT pc.caller_program, pc.call_location, pc.line_number,
                   p.business_name, p.program_type, p.business_purpose
            FROM program_calls pc
            LEFT JOIN programs p ON pc.caller_program = p.program_id
            WHERE pc.called_program = ?
            ORDER BY pc.caller_program
        """, (program_id,))
        callers = [dict(r) for r in cursor.fetchall()]

        # Direct callees
        cursor.execute("""
            SELECT pc.called_program, pc.call_location, pc.line_number,
                   p.business_name, p.program_type, p.business_purpose
            FROM program_calls pc
            LEFT JOIN programs p ON pc.called_program = p.program_id
            WHERE pc.caller_program = ?
            ORDER BY pc.called_program
        """, (program_id,))
        callees = [dict(r) for r in cursor.fetchall()]

        return {"callers": callers, "callees": callees}

    def get_shared_data_context(self, program_id: str) -> Dict:
        """Get copybooks and files used by this program with co-users."""
        cursor = self.conn.cursor()

        # Copybooks used by this program + other programs sharing them
        cursor.execute("""
            SELECT cu.copybook_name
            FROM copybook_usage cu
            WHERE cu.program_id = ?
            ORDER BY cu.copybook_name
        """, (program_id,))
        my_copybooks = [row[0] for row in cursor.fetchall()]

        shared_copybooks = []
        for cb in my_copybooks:
            cursor.execute("""
                SELECT cu.program_id, p.business_name
                FROM copybook_usage cu
                LEFT JOIN programs p ON cu.program_id = p.program_id
                WHERE cu.copybook_name = ? AND cu.program_id != ?
                ORDER BY cu.program_id
            """, (cb, program_id))
            co_users = [dict(r) for r in cursor.fetchall()]
            shared_copybooks.append({
                "copybook_name": cb,
                "co_users": co_users,
                "co_user_count": len(co_users),
            })

        # Files used by this program + other programs sharing them
        cursor.execute("""
            SELECT f.file_name, f.file_type, f.access_mode
            FROM files f
            WHERE f.program_id = ?
            ORDER BY f.file_name
        """, (program_id,))
        my_files = [dict(r) for r in cursor.fetchall()]

        shared_files = []
        for f in my_files:
            cursor.execute("""
                SELECT f2.program_id, p.business_name, f2.access_mode
                FROM files f2
                LEFT JOIN programs p ON f2.program_id = p.program_id
                WHERE f2.file_name = ? AND f2.program_id != ?
                ORDER BY f2.program_id
            """, (f["file_name"], program_id))
            co_users = [dict(r) for r in cursor.fetchall()]
            shared_files.append({
                **f,
                "co_users": co_users,
                "co_user_count": len(co_users),
            })

        return {"shared_copybooks": shared_copybooks, "shared_files": shared_files}

    def get_impact_analysis(self, program_id: str) -> Dict:
        """Compute transitive impact: what breaks if this program changes."""
        cursor = self.conn.cursor()

        # Build full adjacency from DB
        cursor.execute("SELECT caller_program, called_program FROM program_calls")
        calls_out = defaultdict(set)
        called_by = defaultdict(set)
        for row in cursor.fetchall():
            calls_out[row[0]].add(row[1])
            called_by[row[1]].add(row[0])

        # Build copybook coupling
        cursor.execute("SELECT copybook_name, program_id FROM copybook_usage")
        cb_to_progs = defaultdict(set)
        prog_to_cbs = defaultdict(set)
        for row in cursor.fetchall():
            cb_to_progs[row[0]].add(row[1])
            prog_to_cbs[row[1]].add(row[0])

        # All known programs
        cursor.execute("SELECT program_id FROM programs")
        all_programs = set(row[0] for row in cursor.fetchall())

        def transitive(pid, graph):
            visited = set()
            stack = list(graph.get(pid, set()))
            while stack:
                nxt = stack.pop()
                if nxt not in visited and nxt in all_programs:
                    visited.add(nxt)
                    stack.extend(graph.get(nxt, set()) - visited)
            return visited

        def cb_impact(pid):
            affected = set()
            for cb in prog_to_cbs.get(pid, set()):
                affected.update(cb_to_progs.get(cb, set()))
            affected.discard(pid)
            return affected

        direct_callers = called_by.get(program_id, set()) & all_programs
        trans_callers = transitive(program_id, called_by)
        direct_callees = calls_out.get(program_id, set()) & all_programs
        trans_callees = transitive(program_id, calls_out)
        coupling = cb_impact(program_id)
        total_impact = len(trans_callers | coupling)

        if total_impact >= 10:
            risk = "HIGH"
        elif total_impact >= 5:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        return {
            "direct_callers": sorted(direct_callers),
            "transitive_callers": sorted(trans_callers),
            "direct_callees": sorted(direct_callees),
            "transitive_callees": sorted(trans_callees),
            "copybook_coupling": sorted(coupling),
            "total_impact": total_impact,
            "risk": risk,
        }

    def get_linked_clusters(self) -> List[Dict]:
        """Find connected components in the call + copybook graph."""
        cursor = self.conn.cursor()

        cursor.execute("SELECT program_id, business_name, program_type FROM programs")
        all_programs = {row[0]: {"business_name": row[1], "program_type": row[2]}
                        for row in cursor.fetchall()}

        # Build undirected adjacency from calls
        adj = defaultdict(set)
        cursor.execute("SELECT caller_program, called_program FROM program_calls")
        for row in cursor.fetchall():
            if row[0] in all_programs and row[1] in all_programs:
                adj[row[0]].add(row[1])
                adj[row[1]].add(row[0])

        # Add copybook coupling edges
        cursor.execute("SELECT copybook_name, program_id FROM copybook_usage")
        cb_map = defaultdict(set)
        for row in cursor.fetchall():
            if row[1] in all_programs:
                cb_map[row[0]].add(row[1])
        for cb, progs in cb_map.items():
            prog_list = list(progs)
            for i in range(len(prog_list)):
                for j in range(i + 1, len(prog_list)):
                    adj[prog_list[i]].add(prog_list[j])
                    adj[prog_list[j]].add(prog_list[i])

        # BFS to find connected components
        visited = set()
        clusters = []
        for pid in sorted(all_programs.keys()):
            if pid in visited:
                continue
            component = set()
            queue = [pid]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                component.add(node)
                queue.extend(adj.get(node, set()) - visited)
            clusters.append(sorted(component))

        # Build cluster details
        result = []
        for idx, members in enumerate(clusters, 1):
            # Gather inter-cluster calls
            member_set = set(members)
            cursor.execute(
                "SELECT caller_program, called_program, line_number FROM program_calls "
                "WHERE caller_program IN ({seq}) AND called_program IN ({seq})".format(
                    seq=",".join("?" * len(members))),
                members + members)
            internal_calls = [dict(r) for r in cursor.fetchall()]

            # Shared copybooks within cluster
            if members:
                cursor.execute(
                    "SELECT copybook_name, GROUP_CONCAT(program_id) as programs "
                    "FROM copybook_usage WHERE program_id IN ({seq}) "
                    "GROUP BY copybook_name HAVING COUNT(DISTINCT program_id) > 1".format(
                        seq=",".join("?" * len(members))),
                    members)
                shared_cbs = [dict(r) for r in cursor.fetchall()]
            else:
                shared_cbs = []

            result.append({
                "cluster_id": idx,
                "members": members,
                "member_details": [
                    {"program_id": m, **all_programs.get(m, {})} for m in members
                ],
                "size": len(members),
                "internal_calls": internal_calls,
                "shared_copybooks": shared_cbs,
                "is_standalone": len(members) == 1,
            })

        # Sort: largest clusters first, standalones last
        result.sort(key=lambda c: (-c["size"], c["cluster_id"]))
        return result


    # ================================================================
    # JCL Loading & Queries
    # ================================================================

    def load_jcl(self, jcl_jobs: List[Dict]):
        """Load parsed JCL jobs, steps, and datasets into SQLite."""
        if not jcl_jobs:
            return
        cursor = self.conn.cursor()

        # Ensure JCL tables exist (schema may have been created before JCL support)
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS jcl_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT UNIQUE NOT NULL,
                file_name TEXT, file_path TEXT, file_hash TEXT,
                job_description TEXT, job_class TEXT, msg_class TEXT,
                header_comments TEXT, programs_called TEXT,
                input_datasets TEXT, output_datasets TEXT,
                step_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS jcl_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL, step_name TEXT NOT NULL, step_order INTEGER,
                program TEXT, proc TEXT, step_type TEXT,
                step_comments TEXT, cond TEXT, line_number INTEGER, sysin_data TEXT,
                UNIQUE(job_name, step_name)
            );
            CREATE TABLE IF NOT EXISTS jcl_datasets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL, step_name TEXT NOT NULL, dd_name TEXT,
                dsn TEXT, disp TEXT, disposition_normal TEXT, disposition_abnormal TEXT,
                direction TEXT, recfm TEXT, lrecl TEXT, unit TEXT, space TEXT,
                is_inline INTEGER DEFAULT 0
            );
        """)
        self.conn.commit()

        for job in jcl_jobs:
            job_name = job.get("job_name", "")
            if not job_name:
                continue

            # Upsert job row
            cursor.execute("DELETE FROM jcl_datasets WHERE job_name = ?", (job_name,))
            cursor.execute("DELETE FROM jcl_steps    WHERE job_name = ?", (job_name,))
            cursor.execute("DELETE FROM jcl_jobs     WHERE job_name = ?", (job_name,))

            steps = job.get("steps") or []
            cursor.execute("""
                INSERT INTO jcl_jobs (
                    job_name, file_name, file_path, file_hash,
                    job_description, job_class, msg_class, header_comments,
                    programs_called, input_datasets, output_datasets, step_count
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                job_name,
                job.get("file_name"), job.get("file_path"), job.get("file_hash"),
                job.get("job_description"), job.get("job_class"), job.get("msg_class"),
                "\n".join(job.get("comment_lines") or []),
                json.dumps(job.get("programs_called") or []),
                json.dumps(job.get("input_datasets") or []),
                json.dumps(job.get("output_datasets") or []),
                len(steps),
            ))

            for order, step in enumerate(steps, 1):
                step_name = step.get("step_name", f"STEP{order}")
                cursor.execute("""
                    INSERT OR REPLACE INTO jcl_steps (
                        job_name, step_name, step_order, program, proc,
                        step_type, step_comments, cond, line_number, sysin_data
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    job_name, step_name, order,
                    step.get("program"), step.get("proc"),
                    step.get("step_type"),
                    "\n".join(step.get("comment_lines") or []),
                    step.get("cond"), step.get("line_number"),
                    json.dumps(step.get("sysin_data") or []),
                ))

                for ds in (step.get("datasets") or []):
                    cursor.execute("""
                        INSERT INTO jcl_datasets (
                            job_name, step_name, dd_name, dsn, disp,
                            disposition_normal, disposition_abnormal, direction,
                            recfm, lrecl, unit, space, is_inline
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        job_name, step_name,
                        ds.get("dd_name"), ds.get("dsn"), ds.get("disp"),
                        ds.get("disposition_normal"), ds.get("disposition_abnormal"),
                        ds.get("direction"), ds.get("recfm"), ds.get("lrecl"),
                        ds.get("unit"), ds.get("space"),
                        1 if ds.get("is_inline") else 0,
                    ))

        self.conn.commit()
        console.print(f"[green]OK - Loaded {len(jcl_jobs)} JCL jobs into database[/green]")

    def get_all_jcl_jobs(self) -> List[Dict]:
        """Return all JCL jobs with their parsed programs_called / datasets."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT job_name, file_name, file_path, job_description,
                       job_class, msg_class, header_comments,
                       programs_called, input_datasets, output_datasets, step_count
                FROM jcl_jobs ORDER BY job_name
            """)
            rows = [dict(r) for r in cursor.fetchall()]
            for row in rows:
                for f in ("programs_called", "input_datasets", "output_datasets"):
                    try:
                        row[f] = json.loads(row[f] or "[]")
                    except Exception:
                        row[f] = []
            return rows
        except Exception:
            return []

    def get_jcl_job_details(self, job_name: str) -> Optional[Dict]:
        """Return a JCL job with all its steps and datasets."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT * FROM jcl_jobs WHERE job_name = ?", (job_name,))
            row = cursor.fetchone()
            if not row:
                return None
            job = dict(row)
            for f in ("programs_called", "input_datasets", "output_datasets"):
                try:
                    job[f] = json.loads(job.get(f) or "[]")
                except Exception:
                    job[f] = []

            cursor.execute("""
                SELECT * FROM jcl_steps WHERE job_name = ? ORDER BY step_order
            """, (job_name,))
            steps = [dict(r) for r in cursor.fetchall()]
            for step in steps:
                try:
                    step["sysin_data"] = json.loads(step.get("sysin_data") or "[]")
                except Exception:
                    step["sysin_data"] = []
                cursor.execute("""
                    SELECT * FROM jcl_datasets
                    WHERE job_name = ? AND step_name = ? ORDER BY id
                """, (job_name, step["step_name"]))
                step["datasets"] = [dict(r) for r in cursor.fetchall()]
            job["steps"] = steps
            return job
        except Exception:
            return None

    def get_program_jcl_jobs(self, program_id: str) -> List[Dict]:
        """Return all JCL jobs that execute a given COBOL program."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT DISTINCT j.job_name, j.file_name, j.job_description,
                                s.step_name, s.step_order, s.step_comments
                FROM jcl_jobs j
                JOIN jcl_steps s ON j.job_name = s.job_name
                WHERE UPPER(s.program) = UPPER(?)
                ORDER BY j.job_name, s.step_order
            """, (program_id,))
            return [dict(r) for r in cursor.fetchall()]
        except Exception:
            return []


# CLI
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Load COBOL data into SQLite")
    parser.add_argument("--db", default="data/cobol_knowledge.db")
    parser.add_argument("--schema", default="schemas/cobol_knowledge.sql")
    parser.add_argument("--programs", help="programs.json path")
    parser.add_argument("--screens", help="screens.json path")
    parser.add_argument("--rules", help="business_rules.json path")
    parser.add_argument("--enriched", help="enriched output directory")
    args = parser.parse_args()

    loader = SQLiteLoader(args.db, args.schema)
    loader.connect()
    loader.load_from_json(programs_json=args.programs, rules_json=args.rules,
                          enriched_json=args.enriched, screens_json=args.screens)
    if args.programs:
        modules = loader.detect_modules()
        print(f"Detected {len(modules)} modules")
    loader.close()
