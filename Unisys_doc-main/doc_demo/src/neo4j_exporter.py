"""
Neo4j Graph Database Exporter
Exports COBOL analysis data from SQLite to Neo4j for graph visualization.
"""

import os
from typing import Dict, List, Any, Optional
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


class Neo4jExporter:
    """Exports COBOL data to Neo4j graph database."""
    
    def __init__(
        self,
        uri: str = None,
        user: str = None,
        password: str = None
    ):
        """
        Initialize Neo4j exporter.
        
        Args:
            uri: Neo4j connection URI (default: bolt://localhost:7687)
            user: Neo4j username
            password: Neo4j password
        """
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")
        self.driver = None
    
    def connect(self):
        """Connect to Neo4j database."""
        try:
            from neo4j import GraphDatabase
            
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
            # Test connection
            with self.driver.session() as session:
                session.run("RETURN 1")
            
            console.print(f"[green]✓ Connected to Neo4j at {self.uri}[/green]")
            
        except ImportError:
            console.print("[red]Error: neo4j package not installed. Run: pip install neo4j[/red]")
            raise
        except Exception as e:
            console.print(f"[red]Error connecting to Neo4j: {e}[/red]")
            raise
    
    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
            self.driver = None
    
    def clear_database(self):
        """Clear all nodes and relationships."""
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        console.print("[yellow]Cleared existing graph data[/yellow]")
    
    def create_constraints(self):
        """Create uniqueness constraints for node types."""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Program) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (para:Paragraph) REQUIRE para.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (f:File) REQUIRE f.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:DataItem) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:BusinessRule) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Screen) REQUIRE s.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Module) REQUIRE m.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (cb:Copybook) REQUIRE cb.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (j:JclJob) REQUIRE j.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:DbTable) REQUIRE t.name IS UNIQUE",
        ]
        
        with self.driver.session() as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    # Constraint may already exist
                    pass
        
        console.print("[cyan]Created graph constraints[/cyan]")
    
    def export_from_sqlite(self, db_loader):
        """
        Export all data from SQLite to Neo4j.
        
        Args:
            db_loader: SQLiteLoader instance with loaded data
        """
        console.print("[cyan]Exporting to Neo4j...[/cyan]")
        
        self.create_constraints()
        
        # Export programs
        self._export_programs(db_loader)

        # Export modules
        self._export_modules(db_loader)

        # Export files
        self._export_files(db_loader)

        # Export business rules
        self._export_business_rules(db_loader)

        # Export screens (BMS)
        self._export_screens(db_loader)

        # Export copybooks
        self._export_copybooks(db_loader)

        # Export JCL jobs
        self._export_jcl_jobs(db_loader)

        # Export CICS commands
        self._export_cics_commands(db_loader)

        # Export EXEC SQL statements + DB tables
        self._export_sql_operations(db_loader)

        # Export relationships (calls + performs)
        self._export_relationships(db_loader)

        console.print("[green]✓ Neo4j export complete[/green]")
    
    def _export_programs(self, db_loader):
        """Export program nodes."""
        programs = db_loader.get_all_programs()
        
        console.print(f"  Exporting {len(programs)} programs...")
        
        with self.driver.session() as session:
            for prog in programs:
                session.run("""
                    MERGE (p:Program {id: $id})
                    SET p.name = $name,
                        p.type = $type,
                        p.businessName = $businessName,
                        p.businessPurpose = $businessPurpose,
                        p.lineCount = $lineCount,
                        p.filePath = $filePath
                """, {
                    "id": prog["program_id"],
                    "name": prog["program_id"],
                    "type": prog.get("program_type", "BATCH"),
                    "businessName": prog.get("business_name"),
                    "businessPurpose": prog.get("business_purpose"),
                    "lineCount": prog.get("line_count", 0),
                    "filePath": prog.get("file_path")
                })
                
                # Export paragraphs for this program
                details = db_loader.get_program_details(prog["program_id"])
                if details:
                    for para in details.get("paragraphs", []):
                        para_id = f"{prog['program_id']}:{para['paragraph_name']}"
                        session.run("""
                            MERGE (para:Paragraph {id: $id})
                            SET para.name = $name,
                                para.businessName = $businessName,
                                para.lineStart = $lineStart,
                                para.lineEnd = $lineEnd
                            WITH para
                            MATCH (p:Program {id: $programId})
                            MERGE (p)-[:CONTAINS]->(para)
                        """, {
                            "id": para_id,
                            "name": para["paragraph_name"],
                            "businessName": para.get("business_name"),
                            "lineStart": para.get("line_start"),
                            "lineEnd": para.get("line_end"),
                            "programId": prog["program_id"]
                        })
    
    def _export_modules(self, db_loader):
        """Export module nodes and relationships."""
        modules = db_loader.detect_modules()
        
        console.print(f"  Exporting {len(modules)} modules...")
        
        with self.driver.session() as session:
            for module in modules:
                session.run("""
                    MERGE (m:Module {id: $id})
                    SET m.name = $name
                """, {
                    "id": module["module_id"],
                    "name": module["module_name"]
                })
                
                # Link programs to modules
                for prog_id in module["programs"]:
                    session.run("""
                        MATCH (m:Module {id: $moduleId})
                        MATCH (p:Program {id: $programId})
                        MERGE (m)-[:CONTAINS]->(p)
                    """, {
                        "moduleId": module["module_id"],
                        "programId": prog_id
                    })
    
    def _export_files(self, db_loader):
        """Export file nodes."""
        programs = db_loader.get_all_programs()
        
        files_exported = set()
        
        with self.driver.session() as session:
            for prog in programs:
                details = db_loader.get_program_details(prog["program_id"])
                if details:
                    for file in details.get("files", []):
                        file_name = file["file_name"]
                        
                        if file_name not in files_exported:
                            session.run("""
                                MERGE (f:File {name: $name})
                                SET f.type = $type,
                                    f.businessName = $businessName
                            """, {
                                "name": file_name,
                                "type": file.get("file_type", "SEQUENTIAL"),
                                "businessName": file.get("business_name")
                            })
                            files_exported.add(file_name)
                        
                        # Create relationship
                        access = file.get("access_mode", "READ").upper()
                        rel_type = "READS" if "READ" in access else "WRITES"
                        
                        session.run(f"""
                            MATCH (p:Program {{id: $programId}})
                            MATCH (f:File {{name: $fileName}})
                            MERGE (p)-[:{rel_type}]->(f)
                        """, {
                            "programId": prog["program_id"],
                            "fileName": file_name
                        })
        
        console.print(f"  Exported {len(files_exported)} files...")
    
    def _export_business_rules(self, db_loader):
        """Export business rule nodes."""
        rules = db_loader.get_all_business_rules()
        
        console.print(f"  Exporting {len(rules)} business rules...")
        
        with self.driver.session() as session:
            for rule in rules:
                session.run("""
                    MERGE (r:BusinessRule {id: $id})
                    SET r.name = $name,
                        r.statement = $statement,
                        r.category = $category
                    WITH r
                    MATCH (p:Program {id: $programId})
                    MERGE (p)-[:APPLIES]->(r)
                """, {
                    "id": rule["rule_id"],
                    "name": rule["rule_name"],
                    "statement": rule["rule_statement"],
                    "category": rule.get("category", "GENERAL"),
                    "programId": rule["program_id"]
                })
    
    def _export_screens(self, db_loader):
        """Export BMS screen nodes and link to programs."""
        screens = db_loader.get_all_screens()

        console.print(f"  Exporting {len(screens)} screens...")

        with self.driver.session() as session:
            for screen in screens:
                screen_name = screen.get("screen_name") or screen.get("map_name") or "UNKNOWN"
                session.run("""
                    MERGE (s:Screen {name: $name})
                    SET s.mapName = $mapName,
                        s.mapsetName = $mapsetName,
                        s.businessName = $businessName,
                        s.filePath = $filePath
                """, {
                    "name": screen_name,
                    "mapName": screen.get("map_name"),
                    "mapsetName": screen.get("mapset_name"),
                    "businessName": screen.get("business_name"),
                    "filePath": screen.get("file_path"),
                })

                # Link screen to its associated program
                prog = screen.get("associated_program")
                if prog:
                    session.run("""
                        MATCH (p:Program {id: $programId})
                        MATCH (s:Screen {name: $screenName})
                        MERGE (p)-[:USES_SCREEN]->(s)
                    """, {
                        "programId": prog,
                        "screenName": screen_name,
                    })

                # Export screen fields as properties (compact)
                field_names = screen.get("field_names")
                if field_names:
                    session.run("""
                        MATCH (s:Screen {name: $name})
                        SET s.fields = $fields
                    """, {
                        "name": screen_name,
                        "fields": field_names,
                    })

    def _export_copybooks(self, db_loader):
        """Export copybook nodes and INCLUDES relationships."""
        copybooks = db_loader.get_copybooks()

        console.print(f"  Exporting {len(copybooks)} copybooks...")

        with self.driver.session() as session:
            for cb in copybooks:
                cb_name = cb["copybook_name"]
                session.run("""
                    MERGE (cb:Copybook {name: $name})
                    SET cb.filePath = $filePath,
                        cb.businessName = $businessName,
                        cb.description = $description
                """, {
                    "name": cb_name,
                    "filePath": cb.get("file_path"),
                    "businessName": cb.get("business_name"),
                    "description": cb.get("description"),
                })

                # Link programs that use this copybook
                used_by = cb.get("used_by") or ""
                for prog_id in [p.strip() for p in used_by.split(",") if p.strip()]:
                    session.run("""
                        MATCH (p:Program {id: $programId})
                        MATCH (cb:Copybook {name: $cbName})
                        MERGE (p)-[:INCLUDES]->(cb)
                    """, {
                        "programId": prog_id,
                        "cbName": cb_name,
                    })

    def _export_jcl_jobs(self, db_loader):
        """Export JCL job nodes, steps, and EXECUTES relationships."""
        jobs = db_loader.get_all_jcl_jobs()

        console.print(f"  Exporting {len(jobs)} JCL jobs...")

        with self.driver.session() as session:
            for job in jobs:
                job_name = job["job_name"]
                session.run("""
                    MERGE (j:JclJob {name: $name})
                    SET j.fileName = $fileName,
                        j.filePath = $filePath,
                        j.description = $description,
                        j.jobClass = $jobClass,
                        j.stepCount = $stepCount
                """, {
                    "name": job_name,
                    "fileName": job.get("file_name"),
                    "filePath": job.get("file_path"),
                    "description": job.get("job_description"),
                    "jobClass": job.get("job_class"),
                    "stepCount": job.get("step_count", 0),
                })

                # Link JCL job to the COBOL programs it executes
                programs_called = job.get("programs_called") or []
                for prog_id in programs_called:
                    session.run("""
                        MATCH (j:JclJob {name: $jobName})
                        MATCH (p:Program {id: $programId})
                        MERGE (j)-[:EXECUTES]->(p)
                    """, {
                        "jobName": job_name,
                        "programId": prog_id,
                    })

                # Export datasets as properties (input/output DSNs)
                input_ds = job.get("input_datasets") or []
                output_ds = job.get("output_datasets") or []
                if input_ds or output_ds:
                    session.run("""
                        MATCH (j:JclJob {name: $name})
                        SET j.inputDatasets = $inputDs,
                            j.outputDatasets = $outputDs
                    """, {
                        "name": job_name,
                        "inputDs": input_ds,
                        "outputDs": output_ds,
                    })

    def _export_cics_commands(self, db_loader):
        """Export EXEC CICS commands as relationships from programs."""
        cursor = db_loader.conn.cursor()
        try:
            cursor.execute("""
                SELECT program_id, command, paragraph_name, line_number, details_json
                FROM exec_cics ORDER BY program_id, line_number
            """)
            cics_rows = [dict(row) for row in cursor.fetchall()]
        except Exception:
            cics_rows = []

        if not cics_rows:
            console.print("  No CICS commands to export")
            return

        console.print(f"  Exporting {len(cics_rows)} CICS commands...")

        # Group by program for a summary node per program
        from collections import defaultdict
        import json as _json
        by_program = defaultdict(list)
        for row in cics_rows:
            by_program[row["program_id"]].append(row)

        with self.driver.session() as session:
            for prog_id, commands in by_program.items():
                # Create a CicsProfile node summarizing all CICS usage for this program
                cmd_counts = defaultdict(int)
                for c in commands:
                    cmd_counts[c["command"]] += 1

                session.run("""
                    MERGE (cp:CicsProfile {programId: $programId})
                    SET cp.totalCommands = $total,
                        cp.commandSummary = $summary,
                        cp.commands = $commands
                """, {
                    "programId": prog_id,
                    "total": len(commands),
                    "summary": ", ".join(f"{cmd}({cnt})" for cmd, cnt in cmd_counts.items()),
                    "commands": list(cmd_counts.keys()),
                })

                # Link program to its CICS profile
                session.run("""
                    MATCH (p:Program {id: $programId})
                    MATCH (cp:CicsProfile {programId: $programId})
                    MERGE (p)-[:USES_CICS]->(cp)
                """, {
                    "programId": prog_id,
                })

                # Create individual CICS command edges for key commands
                # (SEND MAP, RECEIVE MAP, XCTL, LINK → show screen/program connections)
                for c in commands:
                    details = {}
                    if c.get("details_json"):
                        try:
                            details = _json.loads(c["details_json"])
                        except Exception:
                            pass

                    cmd = c["command"]

                    # SEND/RECEIVE MAP → link program to screen
                    if cmd in ("SEND", "RECEIVE") and details.get("map"):
                        session.run("""
                            MATCH (p:Program {id: $programId})
                            MATCH (s:Screen {name: $mapName})
                            MERGE (p)-[r:CICS_MAP {command: $cmd}]->(s)
                            SET r.lineNumber = $line
                        """, {
                            "programId": prog_id,
                            "mapName": details["map"],
                            "cmd": cmd,
                            "line": c.get("line_number"),
                        })

                    # XCTL/LINK → link program to called program
                    if cmd in ("XCTL", "LINK") and details.get("program"):
                        session.run("""
                            MATCH (p:Program {id: $programId})
                            MATCH (target:Program {id: $targetId})
                            MERGE (p)-[r:CICS_TRANSFER {command: $cmd}]->(target)
                            SET r.lineNumber = $line
                        """, {
                            "programId": prog_id,
                            "targetId": details["program"],
                            "cmd": cmd,
                            "line": c.get("line_number"),
                        })

    def _export_sql_operations(self, db_loader):
        """Export DB2 tables as :DbTable nodes and READS_TABLE / WRITES_TABLE edges."""
        cursor = db_loader.conn.cursor()
        try:
            cursor.execute("""
                SELECT program_id, command, table_name, COUNT(*) as cnt
                FROM exec_sql
                WHERE table_name IS NOT NULL
                GROUP BY program_id, command, table_name
            """)
            sql_rows = [dict(row) for row in cursor.fetchall()]
        except Exception:
            sql_rows = []

        if not sql_rows:
            console.print("  No SQL operations to export")
            return

        console.print(f"  Exporting {len(sql_rows)} SQL access edges...")

        WRITE_CMDS = {"INSERT", "UPDATE", "DELETE", "MERGE"}
        with self.driver.session() as session:
            tables_done = set()
            for r in sql_rows:
                tbl = r["table_name"]
                if tbl not in tables_done:
                    session.run(
                        "MERGE (t:DbTable {name: $name}) "
                        "SET t.label = 'DB2 Table'",
                        {"name": tbl},
                    )
                    tables_done.add(tbl)

                rel = "WRITES_TABLE" if r["command"] in WRITE_CMDS else "READS_TABLE"
                session.run(
                    f"""
                    MATCH (p:Program {{id: $programId}})
                    MATCH (t:DbTable {{name: $tableName}})
                    MERGE (p)-[edge:{rel} {{command: $cmd}}]->(t)
                    SET edge.statementCount = coalesce(edge.statementCount, 0) + $cnt
                    """,
                    {
                        "programId": r["program_id"],
                        "tableName": tbl,
                        "cmd": r["command"],
                        "cnt": r["cnt"],
                    },
                )

    def _export_relationships(self, db_loader):
        """Export CALLS and PERFORMS relationships."""
        call_graph = db_loader.get_call_graph()

        console.print(f"  Exporting {len(call_graph)} call relationships...")

        with self.driver.session() as session:
            for call in call_graph:
                session.run("""
                    MATCH (caller:Program {id: $callerId})
                    MATCH (called:Program {id: $calledId})
                    MERGE (caller)-[r:CALLS]->(called)
                    SET r.lineNumber = $lineNumber
                """, {
                    "callerId": call["caller_program"],
                    "calledId": call["called_program"],
                    "lineNumber": call.get("line_number")
                })

            # Export PERFORMS relationships (intra-program control flow)
            programs = db_loader.get_all_programs()
            perform_count = 0
            for prog in programs:
                details = db_loader.get_program_details(prog["program_id"])
                if not details:
                    continue
                for perf in details.get("performs", []):
                    src_id = f"{prog['program_id']}:{perf['source_paragraph']}"
                    tgt_id = f"{prog['program_id']}:{perf['target_paragraph']}"
                    session.run("""
                        MATCH (src:Paragraph {id: $srcId})
                        MATCH (tgt:Paragraph {id: $tgtId})
                        MERGE (src)-[r:PERFORMS]->(tgt)
                        SET r.type = $perfType,
                            r.lineNumber = $line
                    """, {
                        "srcId": src_id,
                        "tgtId": tgt_id,
                        "perfType": perf.get("perform_type", "SIMPLE"),
                        "line": perf.get("line_number"),
                    })
                    perform_count += 1

            console.print(f"  Exported {perform_count} perform relationships...")
    
    # ============================================
    # Graph Queries for Visualization
    # ============================================
    
    def get_program_dependencies(self, program_id: str, depth: int = 2) -> Dict:
        """
        Get dependency graph for a program.
        
        Args:
            program_id: Program to analyze
            depth: How many levels of dependencies to include
            
        Returns:
            Graph data with nodes and relationships
        """
        with self.driver.session() as session:
            result = session.run(f"""
                MATCH path = (p:Program {{id: $programId}})-[:CALLS*1..{depth}]->(called:Program)
                RETURN path
            """, {"programId": program_id})
            
            nodes = set()
            relationships = []
            
            for record in result:
                path = record["path"]
                for node in path.nodes:
                    nodes.add(node["id"])
                for rel in path.relationships:
                    relationships.append({
                        "from": rel.start_node["id"],
                        "to": rel.end_node["id"],
                        "type": rel.type
                    })
            
            return {
                "nodes": list(nodes),
                "relationships": relationships
            }
    
    def get_impact_analysis(self, program_id: str) -> Dict:
        """
        Find all programs that would be affected by changing a program.
        
        Args:
            program_id: Program being changed
            
        Returns:
            Impact analysis with affected programs
        """
        with self.driver.session() as session:
            # Programs that call this program (directly/indirectly)
            result = session.run("""
                MATCH path = (caller:Program)-[:CALLS*1..5]->(target:Program {id: $programId})
                RETURN DISTINCT caller.id as callerId, 
                       caller.businessName as callerName,
                       length(path) as distance
                ORDER BY distance
            """, {"programId": program_id})
            
            affected = [dict(record) for record in result]
            
            return {
                "target_program": program_id,
                "affected_programs": affected,
                "total_affected": len(affected)
            }
    
    def export_to_csv(self, output_dir: str):
        """
        Export graph data to CSV files for external visualization tools.
        
        Args:
            output_dir: Directory for CSV files
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        with self.driver.session() as session:
            # Export nodes
            result = session.run("""
                MATCH (p:Program)
                RETURN p.id as id, p.name as name, p.type as type, 
                       p.businessName as businessName, 'Program' as label
            """)
            
            with open(output_path / "nodes.csv", 'w') as f:
                f.write("id,name,type,businessName,label\n")
                for record in result:
                    f.write(f"{record['id']},{record['name']},{record['type']},{record['businessName']},Program\n")
            
            # Export relationships
            result = session.run("""
                MATCH (a:Program)-[r:CALLS]->(b:Program)
                RETURN a.id as source, b.id as target, type(r) as type
            """)
            
            with open(output_path / "relationships.csv", 'w') as f:
                f.write("source,target,type\n")
                for record in result:
                    f.write(f"{record['source']},{record['target']},{record['type']}\n")
        
        console.print(f"[green]✓ Exported CSV files to {output_path}[/green]")


# Main entry point
if __name__ == "__main__":
    import argparse
    from sqlite_loader import SQLiteLoader
    
    parser = argparse.ArgumentParser(description="Export COBOL data to Neo4j")
    parser.add_argument("--db", default="data/cobol_knowledge.db", help="SQLite database path")
    parser.add_argument("--uri", help="Neo4j URI (or set NEO4J_URI)")
    parser.add_argument("--user", help="Neo4j user (or set NEO4J_USER)")
    parser.add_argument("--password", help="Neo4j password (or set NEO4J_PASSWORD)")
    parser.add_argument("--clear", action="store_true", help="Clear existing graph data")
    parser.add_argument("--csv", help="Export to CSV files instead")
    
    args = parser.parse_args()
    
    # Load SQLite data
    loader = SQLiteLoader(args.db)
    loader.connect()
    
    # Export to Neo4j
    exporter = Neo4jExporter(
        uri=args.uri,
        user=args.user,
        password=args.password
    )
    exporter.connect()
    
    if args.clear:
        exporter.clear_database()
    
    exporter.export_from_sqlite(loader)
    
    if args.csv:
        exporter.export_to_csv(args.csv)
    
    exporter.close()
    loader.close()
