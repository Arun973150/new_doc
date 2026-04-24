"""
Run the COBOL Documentation Pipeline

Usage:
  python run_pipeline.py                    # Full pipeline (parse + load + docs)
  python run_pipeline.py --skip-parse       # Skip parsing (use existing parsed_output/)
  python run_pipeline.py --skip-enrich      # Skip LLM enrichment
  python run_pipeline.py --enrich           # Enable LLM enrichment (requires GROQ_API_KEY in .env)

Output:
  docs/00-SYSTEM-OVERVIEW.md       # Layer 1: System overview
  docs/modules/*.md                # Layer 2: Module documentation
  docs/programs/*.md               # Layer 3: Program walkthroughs
  docs/business-rules/*.md         # Layer 4: Business rules catalog
  docs/screens/*.md                # Layer 5: Screen catalog
  docs/diagrams/call-graph.md      # Call graph diagram
  docs/data-dictionary.md          # Data dictionary
  docs/copybook-reference.md       # Copybook reference
"""
import sys
sys.path.insert(0, 'src')

from orchestrator import run_pipeline

result = run_pipeline(
    repo_path="carddemo",
    output_dir="docs",
    db_path="data/cobol_knowledge.db",
    schema_path="schemas/cobol_knowledge.sql",
    skip_parse=True,       # Already parsed — using existing parsed_output/
    skip_jcl=True,         # Already parsed — cached jcl_jobs.json will be loaded
    skip_enrich=True,      # Already enriched — using existing enriched_output/
    skip_neo4j=False,      # Export to remote Neo4j
    cobol_format="FIXED",
    groq_model="gemini-2.0-flash",   # Vertex AI model
)
