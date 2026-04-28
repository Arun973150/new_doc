"""
COBOL Documentation Dashboard — Streamlit app
Provides interactive exploration of the parsed and enriched COBOL system:
  - System Overview & Stats
  - Interactive Call Graph (pyvis)
  - Module Structure (all programs)
  - Program Explorer with control flow
  - Migration Readiness Assessment
  - Business Rules Catalog
  - Live Search
"""

import streamlit as st
import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
import sqlite3
import pandas as pd
import tempfile
import io

# Ensure src/ is on path when launched as `streamlit run src/app.py`
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# Force IPv4 for Vertex AI gRPC
os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

from orchestrator import run_pipeline
from sqlite_loader import SQLiteLoader
from doc_agent_pipeline import run_doc_pipeline

st.set_page_config(
    page_title="COBOL Migration Hub",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)
if "open_file_path" not in st.session_state:
    st.session_state.open_file_path = None

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap');

/* ── Base ── */
.main { background-color: #0e1117; }
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* ── Hide default Streamlit sidebar chrome ── */
[data-testid="stSidebarNav"] { display: none !important; }

/* ── Sidebar shell ── */
section[data-testid="stSidebar"] {
    background-color: #1e1e1e;
    border-right: 1px solid #2d2d2d;
    padding: 0 !important;
    min-width: 230px !important;
    max-width: 230px !important;
}
section[data-testid="stSidebar"] > div:first-child { padding: 0 !important; }

/* ── All sidebar buttons: flat, left-aligned ── */
section[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    color: #cccccc !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 13px !important;
    text-align: left !important;
    padding: 5px 10px 5px 14px !important;
    width: 100% !important;
    justify-content: flex-start !important;
    height: auto !important;
    box-shadow: none !important;
    margin: 0 !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #2a2d2e !important;
    color: #ffffff !important;
}

/* ── Active nav item ── */
.nav-active > div > button {
    background-color: #094771 !important;
    color: #ffffff !important;
    border-left: 2px solid #007acc !important;
}

/* ── Sidebar section labels ── */
.sb-section {
    font-size: 10.5px;
    font-weight: 700;
    color: #9d9d9d;
    text-transform: uppercase;
    letter-spacing: 1.3px;
    padding: 14px 14px 4px 14px;
    margin: 0;
    display: block;
}

/* ── Tree file items (non-clickable) ── */
.tree-file {
    font-size: 12.5px;
    color: #bbbbbb;
    padding: 3px 8px 3px 26px;
    font-family: 'Inter', sans-serif;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* ── Expanders in sidebar ── */
section[data-testid="stSidebar"] .streamlit-expanderHeader {
    font-size: 12px !important;
    color: #cccccc !important;
    background: transparent !important;
    padding: 5px 14px !important;
}
section[data-testid="stSidebar"] .streamlit-expanderContent {
    background: transparent !important;
    padding: 0 !important;
    border: none !important;
}

/* ── Main content buttons ── */
.main .stButton > button {
    width: 100%; border-radius: 5px; height: 3em;
    background-color: #262730; color: #00ff00; border: 1px solid #00ff00;
    font-family: 'Inter', sans-serif;
}
.main .stButton > button:hover { background-color: #00ff00; color: #000000; }

/* ── Metric cards ── */
.metric-card {
    padding: 15px; border-radius: 8px; background-color: #1e1e1e;
    border: 1px solid #333; text-align: center;
}
.risk-high   { color: #f85149; font-weight: bold; }
.risk-medium { color: #d29922; font-weight: bold; }
.risk-low    { color: #3fb950; font-weight: bold; }

/* ══ Generated document renderer ══ */
.doc-body {
    font-family: 'Inter', sans-serif;
    font-size: 15px;
    line-height: 1.8;
    color: #d4d4d4;
    max-width: 100%;
    width: 100%;
    padding: 4px 0 32px;
}
.doc-body h1 {
    font-size: 1.75em; font-weight: 700; color: #ffffff;
    border-bottom: 2px solid #2d2d2d; padding-bottom: 10px; margin: 0 0 20px;
}
.doc-body h2 {
    font-size: 1.25em; font-weight: 600; color: #58a6ff;
    margin: 32px 0 10px; padding-left: 10px;
    border-left: 3px solid #1f6feb;
}
.doc-body h3 {
    font-size: 1.05em; font-weight: 600; color: #79c0ff;
    margin: 20px 0 8px;
}
.doc-body h4 { font-size: 0.98em; color: #a5d6ff; margin: 14px 0 6px; }
.doc-body p  { margin: 0 0 14px; }
.doc-body ul, .doc-body ol { padding-left: 22px; margin: 0 0 14px; }
.doc-body li { margin-bottom: 5px; }
.doc-body strong { color: #e8e8e8; font-weight: 600; }
.doc-body em { color: #b8b8b8; font-style: italic; }
.doc-body code {
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 0.85em;
    background: #161b22;
    color: #79c0ff;
    padding: 2px 7px;
    border-radius: 4px;
    border: 1px solid #21262d;
}
.doc-body pre {
    background: #161b22;
    border: 1px solid #21262d;
    border-left: 3px solid #1f6feb;
    border-radius: 6px;
    padding: 14px 18px;
    overflow-x: auto;
    margin: 14px 0;
}
.doc-body pre code {
    background: none; border: none;
    color: #c9d1d9; font-size: 0.88em;
}
.doc-body blockquote {
    border-left: 3px solid #3d444d;
    padding: 2px 0 2px 16px;
    margin: 12px 0;
    color: #8b949e;
}
.doc-body hr { border: none; border-top: 1px solid #2d2d2d; margin: 24px 0; }
.prog-chip {
    display: inline-block;
    background: #0d2b1a;
    color: #3fb950;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82em;
    padding: 1px 7px;
    border-radius: 4px;
    border: 1px solid #1a4731;
    font-weight: 500;
}
</style>
""", unsafe_allow_html=True)

# 
# Helpers
# 

@st.cache_resource
def get_loader():
    db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")
    return SQLiteLoader(db_path)


def db_connect():
    loader = get_loader()
    loader.connect()
    return loader

@st.cache_resource
def get_chat_engine():
    """Initialize KnowledgeBaseChat once, shared across all sessions."""
    from chat_cli import KnowledgeBaseChat
    db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")
    groq_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    return KnowledgeBaseChat(db_path=db_path, groq_api_key=groq_key, model=model)

def search_cobol_files(repo_path, query):
    results = []
    if not repo_path or not os.path.exists(repo_path):
        return results
    for root, _, files in os.walk(repo_path):
        for file in files:
            if file.upper().endswith((".CBL", ".COB", ".CPY")):
                file_path = Path(root) / file
                try:
                    with open(file_path, "r", errors="ignore") as f:
                        for i, line in enumerate(f):
                            if query.lower() in line.lower():
                                results.append({
                                    "file": file, "line": i + 1,
                                    "content": line.strip(),
                                })
                except Exception:
                    pass
    return results


def migration_score(prog: dict) -> int:
    """Score 1-5: how hard to migrate. 5 = hardest."""
    score = 1
    lines = prog.get("line_count", 0) or 0
    if lines > 2000:
        score += 2
    elif lines > 500:
        score += 1
    ptype = prog.get("program_type", "")
    if ptype == "ONLINE":
        score += 1          # CICS screen programs are harder
    bp = prog.get("business_purpose") or ""
    if any(kw in bp.lower() for kw in ["cics", "vsam", "db2", "complex", "batch"]):
        score += 1
    return min(score, 5)


def score_label(s: int) -> str:
    if s >= 4:
        return "High"
    if s == 3:
        return "🟡Medium"
    return "🟢Low"


def render_mermaid(diagram_code: str, height: int = 400):
    """Render a Mermaid diagram using mermaid.js via HTML component."""
    # Strip ```mermaid ... ``` fences if present
    code = diagram_code.strip()
    if code.startswith("```mermaid"):
        code = code[len("```mermaid"):].strip()
    if code.endswith("```"):
        code = code[:-3].strip()

    html = f"""
    <div id="mermaid-container" style="background:#1e1e2e;padding:16px;border-radius:8px;overflow:auto;">
      <div class="mermaid" style="text-align:center;">
{code}
      </div>
    </div>
    <script type="module">
      import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
      mermaid.initialize({{
        startOnLoad: true,
        theme: 'dark',
        themeVariables: {{
          primaryColor: '#58a6ff',
          primaryTextColor: '#c9d1d9',
          primaryBorderColor: '#30363d',
          lineColor: '#8b949e',
          secondaryColor: '#161b22',
          tertiaryColor: '#0d1117',
          background: '#1e1e2e',
          mainBkg: '#1e1e2e',
          nodeBorder: '#30363d',
          clusterBkg: '#161b22',
          titleColor: '#c9d1d9',
          edgeLabelBackground: '#161b22',
          fontSize: '14px'
        }}
      }});
    </script>
    """
    st.components.v1.html(html, height=height, scrolling=True)


# 
# Sidebar
# 

def render_sidebar():
    """VSCode-style left panel: navigation tree + dataset files + pipeline."""

    pages = [
        ("Overview",          "⬡"),
        ("Call Graph",        "◎"),
        ("Dependency Matrix", "⊞"),
        ("Data Flow",         "⇶"),
        ("Modules",           "❏"),
        ("Explorer",          "◈"),
        ("Doc Generator",     "⊕"),
        ("JCL Jobs",          "≡"),
        ("CICS Commands",     "⚙"),
        ("SQL Operations",    "▣"),
        ("Migration",         "⇢"),
        ("Rules",             "⊛"),
        ("Search",            "⌕"),
    ]

    current = st.session_state.get("current_page", "Overview")

    with st.sidebar:
        # ── App header ───────────────────────────────────────────────────────
        st.markdown("""
        <div style="background:#252526;padding:11px 14px 10px;
                    border-bottom:1px solid #3c3c3c;margin-bottom:2px;">
            <span style="font-size:12px;font-weight:700;color:#cccccc;
                         letter-spacing:0.8px;text-transform:uppercase;">
                🔧 COBOL Migration Hub
            </span>
        </div>""", unsafe_allow_html=True)

        # ── Navigation ───────────────────────────────────────────────────────
        st.markdown('<span class="sb-section">Pages</span>', unsafe_allow_html=True)

        for page_name, icon in pages:
            is_active = current == page_name
            if is_active:
                st.markdown('<div class="nav-active">', unsafe_allow_html=True)
            if st.button(f"{icon}  {page_name}", key=f"nav_{page_name}",
                         use_container_width=True):
                st.session_state.current_page = page_name
                st.rerun()
            if is_active:
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div style="height:1px;background:#2d2d2d;margin:8px 0;"></div>',
                    unsafe_allow_html=True)

        # ── Dataset file tree ────────────────────────────────────────────────
        st.markdown('<span class="sb-section">Dataset</span>', unsafe_allow_html=True)

        repo_path = st.session_state.get("_repo_path", "./carddemo/app")

        cbl_files, cpy_files, bms_files = [], [], []
        if repo_path and os.path.exists(repo_path):
            for root, _, files in os.walk(repo_path):
                for f in sorted(files):
                    fu = f.upper()
                    fp = os.path.join(root, f)
                    if fu.endswith((".CBL", ".COB")):
                        cbl_files.append((f, fp))
                    elif fu.endswith(".CPY"):
                        cpy_files.append((f, fp))
                    elif fu.endswith(".BMS"):
                        bms_files.append((f, fp))

        # Programs folder — clicking opens the file viewer
        with st.expander(f"📁 Programs  ({len(cbl_files)})", expanded=False):
            for fname, fp in cbl_files[:60]:
                if st.button(f"📄  {fname}", key=f"tree_cbl_{fname}"):
                    st.session_state.current_page = "File Viewer"
                    st.session_state.open_file_path = fp
                    st.rerun()

        # Copybooks folder — display only
        with st.expander(f"📁 Copybooks  ({len(cpy_files)})", expanded=False):
            for fname, fp in cpy_files[:60]:
                if st.button(f"📄  {fname}", key=f"tree_cpy_{fname}",
                     use_container_width=True):
                    st.session_state.current_page = "File Viewer"
                    st.session_state.open_file_path = fp
                    st.rerun()

        # Screens folder — display only
        with st.expander(f"📁 Screens  ({len(bms_files)})", expanded=False):
            for fname, fp in bms_files[:30]:
                if st.button(f"📄  {fname}", key=f"tree_bms_{fname}",
                     use_container_width=True):
                    st.session_state.current_page = "File Viewer"
                    st.session_state.open_file_path = fp
                    st.rerun()

                    
        st.markdown('<div style="height:1px;background:#2d2d2d;margin:8px 0;"></div>',
                    unsafe_allow_html=True)

        # ── Pipeline controls ────────────────────────────────────────────────
        st.markdown('<span class="sb-section">Pipeline</span>', unsafe_allow_html=True)

        with st.expander("⚙️  Settings & Run", expanded=False):
            repo_path = st.text_input("Repository Path", value="./carddemo/app",
                                      key="_repo_path")
            output_dir = st.text_input("Output Directory", value="docs_streamlit",
                                       key="_output_dir")
            do_parse  = st.checkbox("Parse COBOL (ProLeap)", value=True)
            do_jcl    = st.checkbox("Parse JCL Jobs",        value=True)
            do_enrich = st.checkbox("AI Enrichment (Groq)",  value=False)
            do_neo4j  = st.checkbox("Export to Neo4j",       value=False)

            if st.button("▶  Run Full Pipeline", use_container_width=True):
                with st.status("Executing Pipeline...", expanded=True) as status:
                    run_pipeline(
                        repo_path=repo_path,
                        output_dir=output_dir,
                        skip_parse=not do_parse,
                        skip_jcl=not do_jcl,
                        skip_enrich=not do_enrich,
                        skip_neo4j=not do_neo4j,
                        groq_api_key=os.getenv("GROQ_API_KEY"),
                        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                    )
                    status.update(label="Pipeline Complete!", state="complete",
                                  expanded=False)
                st.success("Documentation generated!")

    return (
        st.session_state.get("_repo_path", "./carddemo/app"),
        st.session_state.get("_output_dir", "docs_streamlit"),
    )

# 
# Tab 1: Overview
# 

def page_overview():
    st.header("System Overview")
    try:
        loader = db_connect()
        programs = loader.get_all_programs()
        rules    = loader.get_all_business_rules()
        screens  = loader.get_all_screens()
        modules  = loader.get_all_modules()
        cg       = loader.get_call_graph()
        loader.close()
    except Exception as e:
        st.error(f"Database not ready — run the pipeline first. ({e})")
        return

    online = [p for p in programs if p.get("program_type") == "ONLINE"]
    batch  = [p for p in programs if p.get("program_type") != "ONLINE"]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Programs", len(programs))
    c2.metric("Online (CICS)", len(online))
    c3.metric("Batch", len(batch))
    c4.metric("Modules", len(modules))
    c5.metric("Business Rules", len(rules))

    c6, c7, c8 = st.columns(3)
    c6.metric("BMS Screens", len(screens))
    c7.metric("Inter-Program Calls", len(cg))
    c8.metric("Enriched Programs", sum(1 for p in programs if p.get("business_purpose")))

    st.divider()
    st.subheader("System Architecture")

    try:
        from pyvis.network import Network as _Network
        _pyvis_ok = True
    except ImportError:
        _pyvis_ok = False

    if not _pyvis_ok:
        st.warning("pyvis not installed — install it with `pip install pyvis` to see the 3-layer graph.")
    else:
        # Query JCL→Program links
        try:
            _db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")
            _conn = sqlite3.connect(_db_path)
            _jcl_df = pd.read_sql_query(
                "SELECT DISTINCT job_name, program FROM jcl_steps "
                "WHERE program IS NOT NULL AND program != ''",
                _conn,
            )
            _cb_df = pd.read_sql_query(
                "SELECT copybook_name, COUNT(*) as cnt FROM copybook_usage "
                "GROUP BY copybook_name HAVING cnt >= 3",
                _conn,
            )
            _conn.close()
            _jcl_rows = [(_r["job_name"], _r["program"]) for _, _r in _jcl_df.iterrows()]
            _top_cbs  = [_r["copybook_name"] for _, _r in _cb_df.iterrows()]
        except Exception:
            _jcl_rows = []
            _top_cbs  = []

        # Build module color maps for this page
        _module_colors = [
            "#58a6ff","#3fb950","#d29922","#f85149","#bc8cff",
            "#39d353","#ff7b72","#79c0ff","#ffa657","#56d364",
            "#e3b341","#db6d28","#388bfd","#f0883e","#7ee787",
        ]
        _prog_to_color  = {}
        _prog_to_module = {}
        for _i, _m in enumerate(modules):
            _c = _module_colors[_i % len(_module_colors)]
            _n = _m.get("business_name") or _m.get("module_name", "")
            for _p in _m.get("programs", []):
                _prog_to_color[_p["program_id"]]  = _c
                _prog_to_module[_p["program_id"]] = _n

        _arch_net = _Network(height="580px", width="100%", bgcolor="#0e1117",
                             font_color="white", directed=True)
        _arch_net.barnes_hut(gravity=-5000, central_gravity=0.4, spring_length=150)

        _added_arch = set()

        # Layer 1: JCL Jobs — triangle, orange
        _jcl_jobs = sorted({r[0] for r in _jcl_rows})
        for _job in _jcl_jobs[:20]:
            _arch_net.add_node(
                f"JOB_{_job}", label=_job,
                color="#f0883e", shape="triangle", size=22,
                title=f"<b>JCL Job: {_job}</b>",
            )
            _added_arch.add(f"JOB_{_job}")

        # Layer 2: Programs — dot, colored by module
        for _prog in programs[:60]:
            _pid = _prog["program_id"]
            _col = _prog_to_color.get(_pid, "#484f58")
            _mod = _prog_to_module.get(_pid, "Unknown")
            _arch_net.add_node(
                _pid, label=_pid,
                color=_col, shape="dot", size=14,
                title=f"<b>{_pid}</b><br>Module: {_mod}<br>Type: {_prog.get('program_type','?')}",
            )
            _added_arch.add(_pid)

        # Layer 3: Key copybooks — square, gold
        for _cb in _top_cbs[:30]:
            _arch_net.add_node(
                f"CB_{_cb}", label=_cb,
                color="#d29922", shape="square", size=10,
                title=f"<b>{_cb}</b><br>Shared Copybook",
            )
            _added_arch.add(f"CB_{_cb}")

        # Edges: JCL → Program (orange)
        for _job, _prog_name in _jcl_rows:
            if f"JOB_{_job}" in _added_arch and _prog_name in _added_arch:
                _arch_net.add_edge(f"JOB_{_job}", _prog_name, color="#f0883e", arrows="to", width=2)

        # Edges: Program → Program (blue)
        for _c in cg[:50]:
            if _c.get("called_program") and _c["called_program"] != "UNKNOWN":
                if _c["caller_program"] in _added_arch and _c["called_program"] in _added_arch:
                    _arch_net.add_edge(_c["caller_program"], _c["called_program"],
                                       color="#58a6ff", arrows="to", width=1)

        # Edges: Program → Copybook (dashed yellow)
        try:
            _db_path2 = os.getenv("DB_PATH", "data/cobol_knowledge.db")
            _conn2 = sqlite3.connect(_db_path2)
            _cu_df = pd.read_sql_query("SELECT program_id, copybook_name FROM copybook_usage", _conn2)
            _conn2.close()
            for _, _row in _cu_df.iterrows():
                _pid2 = _row["program_id"]
                _cb2  = f"CB_{_row['copybook_name']}"
                if _pid2 in _added_arch and _cb2 in _added_arch:
                    _arch_net.add_edge(_pid2, _cb2, color="#d29922", arrows="to",
                                       dashes=True, width=1)
        except Exception:
            pass

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as _f:
            _arch_net.save_graph(_f.name)
            _arch_html_path = _f.name
        with open(_arch_html_path, "r", encoding="utf-8") as _f:
            _arch_html = _f.read()
        st.components.v1.html(_arch_html, height=600, scrolling=False)
        st.caption("JCL Jobs (Layer 1) →  Programs (Layer 2, colors=modules) → 🟡 Shared Copybooks (Layer 3)")

    st.divider()
    st.subheader("Modules at a Glance")
    rows = []
    for m in modules:
        rows.append({
            "Module": m.get("business_name") or m.get("module_name"),
            "Programs": len(m.get("programs", [])),
            "Purpose": (m.get("business_purpose") or m.get("description") or "-")[:80],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# 
# Tab 2: Interactive Call Graph
# 

def page_call_graph():
    st.header("Interactive Call Graph")
    st.caption("Click and drag nodes. Scroll to zoom. Hover for details.")

    try:
        from pyvis.network import Network
    except ImportError:
        st.error("pyvis not installed. Run: `pip install pyvis`")
        return

    try:
        loader = db_connect()
        programs = loader.get_all_programs()
        cg       = loader.get_call_graph()
        modules  = loader.get_all_modules()
        loader.close()
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    # Build module → color map
    module_colors = [
        "#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff",
        "#39d353", "#ff7b72", "#79c0ff", "#ffa657", "#56d364",
        "#e3b341", "#db6d28", "#388bfd", "#f0883e", "#7ee787",
    ]
    prog_to_module = {}
    prog_to_color  = {}
    module_name_list = []
    for i, m in enumerate(modules):
        color = module_colors[i % len(module_colors)]
        name  = m.get("business_name") or m.get("module_name", "")
        if name:
            module_name_list.append(name)
        for p in m.get("programs", []):
            prog_to_module[p["program_id"]] = name
            prog_to_color[p["program_id"]]  = color

    prog_map = {p["program_id"]: p for p in programs}

    #  Filters row 
    col_mod, col_cb = st.columns([3, 1])
    with col_mod:
        selected_module = st.selectbox(
            "Filter by Module",
            ["All Modules"] + sorted(module_name_list),
            key="call_graph_module_filter",
        )
    with col_cb:
        show_copybooks = st.checkbox("Show Copybooks", value=False, key="call_graph_show_copybooks")

    # Apply module filter — keep programs in selected module + their direct neighbours
    if selected_module != "All Modules":
        module_programs = {
            p["program_id"]
            for p in programs
            if prog_to_module.get(p["program_id"]) == selected_module
        }
        # Include direct call neighbours
        neighbour_programs = set()
        for c in cg:
            if c["caller_program"] in module_programs and c.get("called_program") not in (None, "UNKNOWN"):
                neighbour_programs.add(c["called_program"])
            if c.get("called_program") in module_programs:
                neighbour_programs.add(c["caller_program"])
        visible_programs = module_programs | neighbour_programs
        programs_to_show = [p for p in programs if p["program_id"] in visible_programs]
        cg_to_show = [
            c for c in cg
            if c["caller_program"] in visible_programs
            and c.get("called_program") in visible_programs
        ]
    else:
        programs_to_show = programs
        cg_to_show = cg
        visible_programs = {p["program_id"] for p in programs}

    # Query call frequency for edge thickness
    try:
        db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")
        conn_raw = sqlite3.connect(db_path)
        freq_df = pd.read_sql_query(
            "SELECT caller_program, called_program, COUNT(*) as freq "
            "FROM program_calls WHERE called_program != 'UNKNOWN' "
            "GROUP BY caller_program, called_program",
            conn_raw,
        )
        conn_raw.close()
        freq_map = {(row["caller_program"], row["called_program"]): row["freq"] for _, row in freq_df.iterrows()}
    except Exception:
        freq_map = {}

    # Query copybook usage if needed
    copybook_usage = []
    if show_copybooks:
        try:
            db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")
            conn_raw = sqlite3.connect(db_path)
            cb_df = pd.read_sql_query(
                "SELECT program_id, copybook_name FROM copybook_usage", conn_raw
            )
            conn_raw.close()
            copybook_usage = [
                (row["program_id"], row["copybook_name"])
                for _, row in cb_df.iterrows()
                if row["program_id"] in visible_programs
            ]
        except Exception:
            copybook_usage = []

    # Determine entry points and leaf programs
    callers = {c["caller_program"] for c in cg_to_show}
    callees = {c["called_program"]  for c in cg_to_show if c["called_program"] != "UNKNOWN"}
    entry_points = {p["program_id"] for p in programs_to_show if p["program_id"] not in callees}
    leaf_progs   = {p["program_id"] for p in programs_to_show if p["program_id"] not in callers}

    net = Network(height="650px", width="100%", bgcolor="#0e1117",
                  font_color="white", directed=True)
    net.barnes_hut(gravity=-8000, central_gravity=0.3, spring_length=120)

    # Add program nodes
    added = set()
    for prog in programs_to_show:
        pid   = prog["program_id"]
        color = prog_to_color.get(pid, "#484f58")
        shape = "star" if pid in entry_points else ("diamond" if pid in leaf_progs else "dot")
        bname = prog.get("business_name") or pid
        bpurp = (prog.get("business_purpose") or "")[:120]
        mod   = prog_to_module.get(pid, "Unknown")
        tip   = f"<b>{pid}</b><br>{bname}<br>Module: {mod}<br>Type: {prog.get('program_type','?')}<br>Lines: {prog.get('line_count',0)}<br>{bpurp}"
        net.add_node(pid, label=pid, title=tip, color=color, shape=shape, size=18 if pid in entry_points else 12)
        added.add(pid)

    # Add external/unknown call targets if any
    for c in cg_to_show:
        if c["called_program"] and c["called_program"] != "UNKNOWN" and c["called_program"] not in added:
            net.add_node(c["called_program"], label=c["called_program"],
                         color="#f0883e", shape="triangle", size=10,
                         title=f"<b>{c['called_program']}</b><br>External program")
            added.add(c["called_program"])

    # Add copybook nodes
    if show_copybooks:
        cb_nodes_added = set()
        for prog_id, cb_name in copybook_usage:
            if cb_name not in cb_nodes_added:
                net.add_node(
                    f"CB_{cb_name}", label=cb_name,
                    color="#d29922", shape="square", size=10,
                    title=f"<b>{cb_name}</b><br>Copybook",
                )
                cb_nodes_added.add(cb_name)

    # Add program→program edges with frequency-based thickness
    for c in cg_to_show:
        if c.get("called_program") and c["called_program"] != "UNKNOWN":
            freq = freq_map.get((c["caller_program"], c["called_program"]), 1)
            width = max(1, freq * 2)
            net.add_edge(
                c["caller_program"], c["called_program"],
                title=f"Line {c.get('line_number', '?')} | calls: {freq}",
                arrows="to", color="#555", width=width,
            )

    # Add program→copybook edges (dashed gray)
    if show_copybooks:
        for prog_id, cb_name in copybook_usage:
            if prog_id in added:
                net.add_edge(
                    prog_id, f"CB_{cb_name}",
                    title="USES",
                    arrows="to",
                    color="#888888",
                    dashes=True,
                    width=1,
                )

    # Render
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        html_path = f.name

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    st.components.v1.html(html_content, height=670, scrolling=False)

    legend = "**Legend:**  Entry point &nbsp;|&nbsp;  Leaf (no outgoing calls) &nbsp;|&nbsp;  Hub &nbsp;|&nbsp;  External target &nbsp;|&nbsp; *Colors = modules*"
    if show_copybooks:
        legend += " &nbsp;|&nbsp;  Copybook (dashed edge = USES)"
    st.markdown(legend)

    # Call matrix table
    st.subheader("Call Matrix")
    rows = [{"Caller": c["caller_program"],
             "Caller Business Name": c.get("caller_name") or "-",
             "Calls": c["called_program"],
             "Called Business Name": c.get("called_name") or "-",
             "At Line": c.get("line_number") or "-"}
            for c in cg_to_show if c.get("called_program") != "UNKNOWN"]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# 
# Tab: Dependency Matrix
# 

def page_dependency_matrix():
    st.header("Dependency Heatmap")
    st.caption("Shows which programs use which copybooks. Blue = program uses this copybook. Clusters reveal tightly coupled program groups.")

    try:
        import plotly.graph_objects as go
    except ImportError:
        st.error("plotly not installed. Run: `pip install plotly`")
        return

    try:
        db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")
        conn_raw = sqlite3.connect(db_path)
        df = pd.read_sql_query("SELECT program_id, copybook_name FROM copybook_usage", conn_raw)
        conn_raw.close()
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    if df.empty:
        st.warning("No copybook usage data found. Run the pipeline first.")
        return

    # Top 20 most-used copybooks
    top_copybooks = (
        df.groupby("copybook_name")["program_id"]
        .count()
        .sort_values(ascending=False)
        .head(20)
        .index.tolist()
    )
    df_filtered = df[df["copybook_name"].isin(top_copybooks)]

    programs_list = sorted(df_filtered["program_id"].unique().tolist())

    # Build presence matrix
    matrix = []
    for prog in programs_list:
        prog_cbs = set(df_filtered[df_filtered["program_id"] == prog]["copybook_name"].tolist())
        row = [1 if cb in prog_cbs else 0 for cb in top_copybooks]
        matrix.append(row)

    fig = go.Figure(data=go.Heatmap(
        z=matrix,
        x=top_copybooks,
        y=programs_list,
        colorscale=["#0e1117", "#58a6ff"],
        showscale=True,
        hovertemplate="Program: %{y}<br>Copybook: %{x}<br>Uses: %{z}<extra></extra>",
    ))
    fig.update_layout(
        title="Program-Copybook Dependency Matrix",
        xaxis_title="Copybook",
        yaxis_title="Program",
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#c9d1d9"),
        height=max(400, len(programs_list) * 18 + 150),
        xaxis=dict(tickangle=-45),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Blue = program uses this copybook. Clusters reveal tightly coupled program groups.")

    # Summary table
    st.subheader("Top Copybooks by Usage")
    summary = (
        df.groupby("copybook_name")["program_id"]
        .count()
        .reset_index()
        .rename(columns={"program_id": "Programs Using It"})
        .sort_values("Programs Using It", ascending=False)
        .head(30)
    )
    st.dataframe(summary, use_container_width=True, hide_index=True)


# 
# Tab: Data Flow Graph
# 

def page_data_flow():
    st.header("Data Flow Graph")
    st.caption("Shows the flow from JCL Jobs → COBOL Programs → Files/Copybooks.")

    try:
        from pyvis.network import Network
    except ImportError:
        st.error("pyvis not installed. Run: `pip install pyvis`")
        return

    try:
        loader = db_connect()
        all_programs = loader.get_all_programs()
        all_jcl_jobs = loader.get_all_jcl_jobs()
        loader.close()
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    # Query top files from DB
    try:
        db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")
        conn_raw = sqlite3.connect(db_path)
        try:
            files_df = pd.read_sql_query("SELECT program_id, file_name FROM files LIMIT 200", conn_raw)
            prog_file_pairs = [(r["program_id"], r["file_name"]) for _, r in files_df.iterrows()]
        except Exception:
            prog_file_pairs = []
        conn_raw.close()
    except Exception:
        prog_file_pairs = []

    net = Network(height="650px", width="100%", bgcolor="#0e1117",
                  font_color="white", directed=True)
    net.barnes_hut(gravity=-6000, central_gravity=0.35, spring_length=140)

    added = set()

    # JCL Job nodes — triangle, orange
    for job in (all_jcl_jobs or [])[:30]:
        jname = job.get("job_name", "")
        if not jname:
            continue
        node_id = f"JOB_{jname}"
        if node_id not in added:
            net.add_node(node_id, label=jname, color="#f0883e", shape="triangle", size=22,
                         title=f"<b>JCL Job: {jname}</b><br>Steps: {job.get('step_count',0)}")
            added.add(node_id)

    # Program nodes — dot, colored by type
    for prog in all_programs[:80]:
        pid = prog["program_id"]
        ptype = prog.get("program_type", "BATCH")
        color = "#58a6ff" if ptype == "ONLINE" else "#3fb950"
        if pid not in added:
            net.add_node(pid, label=pid, color=color, shape="dot", size=14,
                         title=f"<b>{pid}</b><br>Type: {ptype}<br>Lines: {prog.get('line_count',0)}")
            added.add(pid)

    # File nodes — square, gray
    file_nodes = set()
    for prog_id, file_name in prog_file_pairs:
        if not file_name:
            continue
        fn_id = f"FILE_{file_name}"
        if fn_id not in file_nodes:
            net.add_node(fn_id, label=file_name, color="#6e7681", shape="square", size=10,
                         title=f"<b>File: {file_name}</b>")
            file_nodes.add(fn_id)

    # Edges: JCL Job → Program
    for job in (all_jcl_jobs or [])[:30]:
        jname = job.get("job_name", "")
        programs_called = job.get("programs_called") or []
        jnode = f"JOB_{jname}"
        if jnode not in added:
            continue
        for prog_name in programs_called:
            if prog_name and prog_name in added:
                net.add_edge(jnode, prog_name, color="#f0883e", arrows="to", width=2,
                             title=f"{jname} executes {prog_name}")

    # Edges: Program → File
    for prog_id, file_name in prog_file_pairs:
        if not file_name:
            continue
        fn_id = f"FILE_{file_name}"
        if prog_id in added and fn_id in file_nodes:
            net.add_edge(prog_id, fn_id, color="#6e7681", arrows="to", dashes=True, width=1,
                         title=f"{prog_id} accesses {file_name}")

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        html_path = f.name
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    st.components.v1.html(html_content, height=670, scrolling=False)

    st.markdown("""
**Legend:**
-  **Triangle (orange)** — JCL Job
-  **Circle (blue)** — Online/CICS Program
- 🟢 **Circle (green)** — Batch Program
-  **Square (gray)** — File/Dataset
- Solid arrow = executes / calls &nbsp;|&nbsp; Dashed arrow = file access
""")


# 
# Tab 3: Module Structure (all programs)
# 

def page_modules():
    st.header("Module Structure")
    try:
        loader = db_connect()
        modules = loader.get_all_modules()
        loader.close()
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    for m in modules:
        prog_list = m.get("programs", [])
        name      = m.get("business_name") or m.get("module_name", "")
        purpose   = m.get("business_purpose") or m.get("description") or "-"
        with st.expander(f"**{name}** — {len(prog_list)} programs", expanded=False):
            st.write(f"*{purpose}*")
            rows = []
            for p in prog_list:  # ALL programs — no [:3] limit
                rows.append({
                    "Program ID": p.get("program_id"),
                    "Type": p.get("program_type") or "-",
                    "Lines": p.get("line_count") or 0,
                    "Business Name": p.get("business_name") or "-",
                    "Purpose": (p.get("business_purpose") or "-")[:80],
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def _render_explorer_chat(program_id: str):
    """Sticky WhatsApp-style chat assistant aware of the selected program."""
    chat_key = f"chat_history_{program_id}"
    if chat_key not in st.session_state:
        st.session_state[chat_key] = []

    history = st.session_state[chat_key]

    # Context banner
    st.info(
        f"**Context locked to `{program_id}`** — phrases like "
        f"\"this program\", \"it\", or \"its paragraphs\" all refer to `{program_id}`.",
        icon="🔒",
    )

    col_hint, col_clear = st.columns([3, 1])
    with col_hint:
        st.caption("Ask about control flow, data items, business rules, callers, callees, migration complexity…")
    with col_clear:
        if history and st.button("Clear history", key=f"clr_{program_id}"):
            st.session_state[chat_key] = []
            st.rerun()

    # Render existing conversation
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Sticky input — Streamlit renders chat_input pinned to bottom
    if prompt := st.chat_input(f"Ask about {program_id}…"):
        st.session_state[chat_key].append({"role": "user", "content": prompt})

        try:
            engine = get_chat_engine()
            with st.spinner(""):
                answer = engine.ask(prompt, current_program=program_id)
        except Exception as exc:
            answer = f"⚠ Error: {exc}"

        st.session_state[chat_key].append({"role": "assistant", "content": answer})
        st.rerun()
# 
# Tab 4: Program Explorer
# 
def page_explorer():
    st.header("Program Explorer")
    try:
        loader = db_connect()
        programs = loader.get_all_programs()
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    program_ids = [p["program_id"] for p in programs]
    col_sel, col_filt = st.columns([2, 1])
    with col_filt:
        type_filter = st.selectbox("Filter by type", ["All", "ONLINE", "BATCH"], key="explorer_type_filter")
    with col_sel:
        if type_filter != "All":
            filtered = [p["program_id"] for p in programs if p.get("program_type") == type_filter]
        else:
            filtered = program_ids
        selected = st.selectbox("Select Program", filtered, key="explorer_program_select")

    if not selected:
        loader.close()
        return

    details = loader.get_program_details(selected)
    loader.close()

    if not details:
        st.warning(f"No details found for {selected}")
        return

    # ── ADDED: "Chat Assistant" as fifth tab ──────────────────────────────
    tab_overview, tab_flow, tab_data, tab_rules, tab_chat = st.tabs(
        ["Overview", "Control Flow", "Data Items", "Business Rules", "Chat Assistant"]
    )
    # ──────────────────────────────────────────────────────────────────────

    with tab_overview:
        bname = details.get("business_name") or selected
        st.markdown(f"### {bname}")
        bpurp = details.get("business_purpose")
        if bpurp:
            st.info(bpurp)
        else:
            st.warning("No business purpose extracted yet. Run LLM enrichment.")

        c1, c2, c3 = st.columns(3)
        c1.metric("Type", details.get("program_type") or "-")
        c2.metric("Lines", details.get("line_count") or 0)
        c3.metric("Paragraphs", len(details.get("paragraphs") or []))

        user_role = details.get("user_role")
        bprocess  = details.get("business_process")
        if user_role:
            st.markdown(f"**Used by:** {user_role}")
        if bprocess:
            st.markdown(f"**Business process:** {bprocess}")

        score = migration_score(details)
        st.markdown(f"**Migration complexity:** {score_label(score)} ({score}/5)")

        callers  = details.get("called_by") or []
        callees  = details.get("calls") or []
        st.divider()
        c_in, c_out = st.columns(2)
        with c_in:
            st.markdown(f"**Called by ({len(callers)})**")
            for c in callers:
                st.markdown(f"- `{c['caller_program']}`")
        with c_out:
            st.markdown(f"**Calls ({len(callees)})**")
            for c in callees:
                st.markdown(f"- `{c['called_program']}`")

    with tab_flow:
        paragraphs = details.get("paragraphs") or []
        performs   = details.get("performs") or []

        if not paragraphs:
            st.info("No paragraphs found for this program.")
        else:
            safe_id = lambda s: s.replace("-", "_").replace(" ", "_").replace(".", "_")
            para_by_name = {p.get("paragraph_name", ""): p for p in paragraphs}

            def _para_style(para):
                if bool(para.get("calls", [])):  return "caller"
                if bool(para.get("performs", [])): return "hub"
                return "simple"

            mermaid = "flowchart TD\n    START([Program Entry])\n"
            for para in paragraphs[:20]:
                pname = para.get("paragraph_name", "?")
                bname = (para.get("business_name") or pname).replace('"', "'")
                rule_count = len(para.get("business_rules") or [])
                badge = f"\\n({rule_count} rules)" if rule_count > 0 else ""
                style_cls = _para_style(para)
                mermaid += f'    {safe_id(pname)}["{bname}{badge}"]:::{style_cls}\n'

            if paragraphs:
                mermaid += f'START --> {safe_id(paragraphs[0]["paragraph_name"])}\n'
            seen = set()
            for pf in performs[:30]:
                src = pf.get("source_paragraph") or pf.get("paragraph_name", "")
                tgt = pf.get("target_paragraph") or pf.get("target", "")
                if src and tgt and f"{src}->{tgt}" not in seen:
                    mermaid += f"    {safe_id(src)} --> {safe_id(tgt)}\n"
                    seen.add(f"{src}->{tgt}")

            mermaid += "    classDef caller fill:#f85149,stroke:#ff7b72,color:#fff\n"
            mermaid += "    classDef hub fill:#388bfd,stroke:#58a6ff,color:#fff\n"
            mermaid += "    classDef simple fill:#2ea043,stroke:#3fb950,color:#fff\n"

            render_mermaid(mermaid, height=450)
            st.caption("Caller (calls other programs) | Hub (performs other paragraphs) | 🟢 Simple paragraph")

            st.subheader("Paragraph Narratives")
            para_rows = []
            for p in paragraphs:
                para_rows.append({
                    "Paragraph": p.get("paragraph_name"),
                    "Business Name": p.get("business_name") or "-",
                    "Lines": f"{p.get('line_start','?')}–{p.get('line_end','?')}",
                    "Narrative": (p.get("narrative") or p.get("purpose") or "-")[:120],
                })
            st.dataframe(pd.DataFrame(para_rows), use_container_width=True, hide_index=True)

    with tab_data:
        items = details.get("data_items") or []
        if not items:
            st.info("No data items found.")
        else:
            rows = [{
                "Name": d.get("name"),
                "Level": d.get("level_number") or "-",
                "Picture": d.get("picture") or "-",
                "Section": d.get("section") or "-",
                "Business Name": d.get("business_name") or "-",
                "Description": (d.get("description") or "-")[:80],
            } for d in items if d.get("name") != "FILLER"]
            st.caption(f"{len(rows)} data items (FILLER excluded)")
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with tab_rules:
        rules = details.get("business_rules") or []
        if not rules:
            st.info("No business rules extracted yet. Run LLM enrichment.")
        else:
            for r in rules:
                with st.expander(f"**{r.get('rule_id','?')}** — {r.get('rule_name','?')}", expanded=False):
                    st.markdown(f"**Category:** {r.get('category','-')}")
                    st.markdown(f"**Rule:** {r.get('rule_statement','-')}")
                    st.markdown(f"**When:** {r.get('condition_text') or r.get('condition','-')}")
                    st.markdown(f"**Then:** {r.get('action_text') or r.get('action','-')}")
                    if r.get("paragraph_name"):
                        st.caption(f"Paragraph: {r['paragraph_name']} | Lines: {r.get('line_start','?')}–{r.get('line_end','?')}")

    # ── NEW TAB ───────────────────────────────────────────────────────────
    with tab_chat:
        _render_explorer_chat(selected)
    # ──────────────────────────────────────────────────────────────────────

#
# File Viewer
#

def page_file_viewer():
    """Display the raw source of a COBOL / Copybook / BMS file with line numbers."""
    fp = st.session_state.get("open_file_path")
    if not fp or not os.path.isfile(fp):
        st.warning("No file selected — click a program or copybook in the sidebar.")
        return

    fname = os.path.basename(fp)
    st.header(f"File Viewer — {fname}")
    st.caption(fp)

    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except Exception as e:
        st.error(f"Cannot read file: {e}")
        return

    # Show source with syntax highlighting
    lang = "cobol"
    if fname.upper().endswith(".BMS"):
        lang = "text"
    elif fname.upper().endswith((".JCL", ".JOB")):
        lang = "text"

    st.code(source, language=lang, line_numbers=True)

    # Quick link to explorer if it's a known program
    prog_id = fname.upper().rsplit(".", 1)[0]
    try:
        loader = db_connect()
        details = loader.get_program_details(prog_id)
        loader.close()
        if details:
            if st.button(f"Open {prog_id} in Explorer", use_container_width=True):
                st.session_state.current_page = "Explorer"
                st.session_state.explorer_program_select = prog_id
                st.rerun()
    except Exception:
        pass

#
# CICS Commands
#

def page_cics():
    st.header("CICS Commands")
    st.caption("EXEC CICS commands extracted from COBOL source — screens, transfers, file ops, and more.")

    db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    # Check if exec_cics table exists
    table_check = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='exec_cics'"
    ).fetchone()
    if not table_check:
        st.warning("No `exec_cics` table found. Run the pipeline to populate CICS data.")
        conn.close()
        return

    total = conn.execute("SELECT COUNT(*) FROM exec_cics").fetchone()[0]
    if total == 0:
        st.info("No CICS commands found.")
        conn.close()
        return

    progs_with_cics = conn.execute(
        "SELECT COUNT(DISTINCT program_id) FROM exec_cics"
    ).fetchone()[0]
    distinct_cmds = conn.execute(
        "SELECT COUNT(DISTINCT command) FROM exec_cics"
    ).fetchone()[0]
    unknown_count = conn.execute(
        "SELECT COUNT(*) FROM exec_cics WHERE command='UNKNOWN'"
    ).fetchone()[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Commands", total)
    c2.metric("Programs Using CICS", progs_with_cics)
    c3.metric("Distinct Commands", distinct_cmds)
    c4.metric("Unresolved", unknown_count)

    st.divider()

    # Command type breakdown
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Commands by Type")
        cmd_counts = [dict(r) for r in conn.execute("""
            SELECT command, COUNT(*) as cnt
            FROM exec_cics
            GROUP BY command
            ORDER BY cnt DESC
        """).fetchall()]
        if cmd_counts:
            df = pd.DataFrame(cmd_counts)
            st.bar_chart(df.set_index("command"))

    with col2:
        st.subheader("Top Programs by CICS Usage")
        prog_counts = [dict(r) for r in conn.execute("""
            SELECT ec.program_id, p.business_name, COUNT(*) as cics_count
            FROM exec_cics ec
            LEFT JOIN programs p ON ec.program_id = p.program_id
            GROUP BY ec.program_id
            ORDER BY cics_count DESC
            LIMIT 15
        """).fetchall()]
        if prog_counts:
            st.dataframe(pd.DataFrame(prog_counts),
                         use_container_width=True, hide_index=True, height=400)

    st.divider()

    # Browse with filters
    st.subheader("Browse Commands")
    fc1, fc2, fc3 = st.columns([2, 2, 1])

    all_commands = ["(All)"] + [r["command"] for r in cmd_counts]
    selected_cmd = fc1.selectbox("Filter by command", all_commands, key="cics_cmd_filter")

    all_progs_cics = [dict(r) for r in conn.execute(
        "SELECT DISTINCT program_id FROM exec_cics ORDER BY program_id"
    ).fetchall()]
    prog_options = ["(All)"] + [r["program_id"] for r in all_progs_cics]
    selected_prog = fc2.selectbox("Filter by program", prog_options, key="cics_prog_filter")

    limit = fc3.number_input("Limit", min_value=10, max_value=500, value=100, step=10,
                              key="cics_limit")

    where_clauses = []
    params = []
    if selected_cmd != "(All)":
        where_clauses.append("command = ?")
        params.append(selected_cmd)
    if selected_prog != "(All)":
        where_clauses.append("program_id = ?")
        params.append(selected_prog)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = [dict(r) for r in conn.execute(f"""
        SELECT program_id, command, paragraph_name, line_number, details_json
        FROM exec_cics
        {where_sql}
        ORDER BY program_id, line_number
        LIMIT {int(limit)}
    """, tuple(params)).fetchall()]

    if rows:
        display_rows = []
        for r in rows:
            details_str = "-"
            if r.get("details_json"):
                try:
                    d = json.loads(r["details_json"])
                    inner = d.get("details", d)
                    if isinstance(inner, dict) and inner:
                        details_str = ", ".join(f"{k}={v}" for k, v in inner.items())
                except Exception:
                    pass
            display_rows.append({
                "Program":   r["program_id"],
                "Command":   r["command"],
                "Paragraph": r.get("paragraph_name") or "-",
                "Line":      r.get("line_number") or "-",
                "Details":   details_str,
            })
        st.dataframe(pd.DataFrame(display_rows),
                     use_container_width=True, hide_index=True, height=400)
    else:
        st.info("No commands match the current filters.")

    st.divider()

    # Categorized flows
    st.subheader("CICS-Driven Flows")
    tab1, tab2, tab3 = st.tabs([
        "BMS Screens (SEND/RECEIVE)",
        "Program Transfers (XCTL/LINK)",
        "File Ops (READ/WRITE)",
    ])

    def _detail(r, key):
        if r.get("details_json"):
            try:
                d = json.loads(r["details_json"])
                inner = d.get("details", d) or {}
                return inner.get(key, "-")
            except Exception:
                return "-"
        return "-"

    with tab1:
        screen_ops = [dict(r) for r in conn.execute("""
            SELECT program_id, command, paragraph_name, line_number, details_json
            FROM exec_cics
            WHERE command IN ('SEND', 'RECEIVE')
            ORDER BY program_id, line_number
        """).fetchall()]
        if screen_ops:
            mapped = [{
                "Program": r["program_id"], "Op": r["command"],
                "Map":     _detail(r, "map"),
                "Mapset":  _detail(r, "mapset"),
                "Line":    r.get("line_number") or "-",
            } for r in screen_ops]
            st.dataframe(pd.DataFrame(mapped),
                         use_container_width=True, hide_index=True, height=350)
        else:
            st.info("No SEND/RECEIVE MAP commands found.")

    with tab2:
        transfers = [dict(r) for r in conn.execute("""
            SELECT program_id, command, paragraph_name, line_number, details_json
            FROM exec_cics
            WHERE command IN ('XCTL', 'LINK')
            ORDER BY program_id, line_number
        """).fetchall()]
        if transfers:
            mapped = [{
                "From Program":   r["program_id"], "Op": r["command"],
                "Target Program": _detail(r, "program"),
                "Commarea":       _detail(r, "commarea"),
                "Line":           r.get("line_number") or "-",
            } for r in transfers]
            st.dataframe(pd.DataFrame(mapped),
                         use_container_width=True, hide_index=True, height=350)
        else:
            st.info("No XCTL/LINK commands found.")

    with tab3:
        file_ops = [dict(r) for r in conn.execute("""
            SELECT program_id, command, paragraph_name, line_number, details_json
            FROM exec_cics
            WHERE command IN ('READ', 'WRITE', 'REWRITE', 'DELETE',
                              'STARTBR', 'READNEXT', 'READPREV', 'ENDBR')
            ORDER BY program_id, line_number
        """).fetchall()]
        if file_ops:
            mapped = []
            for r in file_ops:
                ds = _detail(r, "dataset")
                if ds == "-":
                    ds = _detail(r, "file")
                mapped.append({
                    "Program":      r["program_id"], "Op": r["command"],
                    "Dataset/File": ds,
                    "RIDFLD":       _detail(r, "ridfld"),
                    "Line":         r.get("line_number") or "-",
                })
            st.dataframe(pd.DataFrame(mapped),
                         use_container_width=True, hide_index=True, height=350)
        else:
            st.info("No CICS file operations found.")

    conn.close()


#
# SQL Operations (DB2)
#

def page_sql():
    st.header("SQL Operations (DB2)")
    st.caption("EXEC SQL statements extracted from COBOL source — tables, cursors, and DML usage.")

    db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    table_check = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='exec_sql'"
    ).fetchone()
    if not table_check:
        st.warning("No `exec_sql` table found. Run the pipeline to populate SQL data.")
        conn.close()
        return

    total = conn.execute("SELECT COUNT(*) FROM exec_sql").fetchone()[0]
    if total == 0:
        st.info("No SQL statements found in the database.")
        conn.close()
        return

    progs = conn.execute("SELECT COUNT(DISTINCT program_id) FROM exec_sql").fetchone()[0]
    distinct_cmds = conn.execute("SELECT COUNT(DISTINCT command) FROM exec_sql").fetchone()[0]
    distinct_tables = conn.execute("SELECT COUNT(DISTINCT table_name) FROM exec_sql WHERE table_name IS NOT NULL").fetchone()[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total SQL Statements", total)
    c2.metric("Programs Using SQL", progs)
    c3.metric("Distinct Commands", distinct_cmds)
    c4.metric("Distinct Tables", distinct_tables)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Statements by Command Type")
        cmd_counts = [dict(r) for r in conn.execute("""
            SELECT command, COUNT(*) as cnt
            FROM exec_sql GROUP BY command ORDER BY cnt DESC
        """).fetchall()]
        if cmd_counts:
            df = pd.DataFrame(cmd_counts)
            st.bar_chart(df.set_index("command"))

    with col2:
        st.subheader("Top Tables by Access Count")
        table_counts = [dict(r) for r in conn.execute("""
            SELECT table_name, COUNT(*) as cnt
            FROM exec_sql WHERE table_name IS NOT NULL
            GROUP BY table_name ORDER BY cnt DESC LIMIT 15
        """).fetchall()]
        if table_counts:
            st.dataframe(pd.DataFrame(table_counts),
                         use_container_width=True, hide_index=True, height=400)

    st.divider()

    # Cross-program table access matrix
    st.subheader("Table Access Matrix (Programs ↔ Tables)")
    st.caption("Shows which programs read or write which tables — the basis for data-flow analysis.")
    matrix_rows = [dict(r) for r in conn.execute("""
        SELECT program_id, table_name, command, COUNT(*) as cnt
        FROM exec_sql WHERE table_name IS NOT NULL
        GROUP BY program_id, table_name, command
        ORDER BY program_id, table_name
    """).fetchall()]
    if matrix_rows:
        df = pd.DataFrame(matrix_rows)
        df["op"] = df["command"].map({
            "SELECT": "READ", "FETCH": "READ", "DECLARE": "READ",
            "INSERT": "WRITE", "UPDATE": "WRITE", "DELETE": "WRITE", "MERGE": "WRITE",
        }).fillna(df["command"])
        st.dataframe(df, use_container_width=True, hide_index=True, height=350)

    st.divider()

    # Filter view
    st.subheader("Browse SQL Statements")
    fc1, fc2, fc3 = st.columns([2, 2, 1])
    all_progs = ["(All)"] + [r["program_id"] for r in conn.execute(
        "SELECT DISTINCT program_id FROM exec_sql ORDER BY program_id"
    ).fetchall()]
    sel_prog = fc1.selectbox("Filter by program", all_progs, key="sql_prog_filter")
    all_cmds = ["(All)"] + [r["command"] for r in cmd_counts]
    sel_cmd = fc2.selectbox("Filter by command", all_cmds, key="sql_cmd_filter")
    limit = fc3.number_input("Limit", min_value=10, max_value=500, value=100, step=10,
                              key="sql_limit")

    where = []
    params = []
    if sel_prog != "(All)":
        where.append("program_id = ?")
        params.append(sel_prog)
    if sel_cmd != "(All)":
        where.append("command = ?")
        params.append(sel_cmd)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = [dict(r) for r in conn.execute(
        f"SELECT program_id, command, table_name, cursor_name, paragraph_name, line_number, sql_text "
        f"FROM exec_sql {where_sql} ORDER BY program_id, line_number LIMIT {int(limit)}",
        tuple(params)
    ).fetchall()]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=400)
    else:
        st.info("No SQL statements match the filters.")

    conn.close()


#
# Tab 5: JCL Jobs
#

def page_jcl():
    st.header("JCL Jobs")
    st.caption("Batch JCL jobs parsed from the repository — which programs they run, what files they read/write.")

    try:
        loader = db_connect()
        jobs = loader.get_all_jcl_jobs()
        loader.close()
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    if not jobs:
        st.warning("No JCL jobs found. Run the pipeline with 'Parse JCL Jobs' checked.")
        return

    st.metric("Total JCL Jobs", len(jobs))
    st.divider()

    # Summary table
    rows = []
    for job in jobs:
        rows.append({
            "Job Name":        job.get("job_name"),
            "File":            job.get("file_name"),
            "Description":     (job.get("job_description") or "-")[:60],
            "Steps":           job.get("step_count", 0),
            "Programs Called": ", ".join(job.get("programs_called") or []) or "-",
            "Input Datasets":  len(job.get("input_datasets") or []),
            "Output Datasets": len(job.get("output_datasets") or []),
        })
    st.subheader("All JCL Jobs")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()

    # Detail view
    st.subheader("Job Detail")
    job_names = [j["job_name"] for j in jobs]
    selected_job = st.selectbox("Select Job", job_names, key="jcl_job_select")

    if selected_job:
        try:
            loader = db_connect()
            detail = loader.get_jcl_job_details(selected_job)
            loader.close()
        except Exception as e:
            st.error(str(e))
            return

        if not detail:
            st.warning("No details found.")
            return

        if detail.get("header_comments"):
            st.markdown("**Job Description (Header Comments)**")
            st.code(detail["header_comments"], language=None)

        c1, c2, c3 = st.columns(3)
        c1.metric("Steps", len(detail.get("steps") or []))
        c2.metric("Input Datasets", len(detail.get("input_datasets") or []))
        c3.metric("Output Datasets", len(detail.get("output_datasets") or []))

        if detail.get("programs_called"):
            st.markdown("**COBOL Programs Executed**")
            for p in detail["programs_called"]:
                st.markdown(f"- `{p}`")

        if detail.get("input_datasets"):
            st.markdown("**Input Datasets**")
            for d in detail["input_datasets"]:
                st.code(d, language=None)

        if detail.get("output_datasets"):
            st.markdown("**Output Datasets**")
            for d in detail["output_datasets"]:
                st.code(d, language=None)

        st.subheader("Steps")
        for step in (detail.get("steps") or []):
            with st.expander(
                f"Step {step.get('step_order','?')}: **{step.get('step_name')}** "
                f"— {step.get('step_type','?')} "
                f"{'`' + step['program'] + '`' if step.get('program') else ''}"
            ):
                if step.get("step_comments"):
                    st.info(step["step_comments"])

                datasets = step.get("datasets") or []
                if datasets:
                    dd_rows = []
                    for ds in datasets:
                        if not ds.get("is_inline"):
                            dd_rows.append({
                                "DD Name":   ds.get("dd_name"),
                                "Dataset":   ds.get("dsn") or "-",
                                "DISP":      ds.get("disp") or "-",
                                "Direction": ds.get("direction") or "-",
                                "RECFM":     ds.get("recfm") or "-",
                                "LRECL":     ds.get("lrecl") or "-",
                            })
                    if dd_rows:
                        st.dataframe(pd.DataFrame(dd_rows), use_container_width=True, hide_index=True)

                if step.get("sysin_data"):
                    st.markdown("**Inline SYSIN**")
                    st.code("\n".join(step["sysin_data"]), language=None)


# 
# Tab 6 (was 5): Migration Readiness
# 

def page_migration():
    st.header("Migration Readiness")
    st.markdown("""
This page scores each program by migration complexity and suggests a migration order.
**Migrate leaf programs first** (no outgoing calls), then work up the dependency chain.
""")
    try:
        loader = db_connect()
        programs = loader.get_all_programs()
        cg       = loader.get_call_graph()
        loader.close()
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    callers = {c["caller_program"] for c in cg}
    callees = {c["called_program"]  for c in cg if c["called_program"] != "UNKNOWN"}

    rows = []
    for p in programs:
        pid   = p["program_id"]
        score = migration_score(p)
        is_leaf  = pid not in callers
        is_entry = pid not in callees
        outgoing = len([c for c in cg if c["caller_program"] == pid and c.get("called_program") != "UNKNOWN"])
        incoming = len([c for c in cg if c["called_program"] == pid])
        rows.append({
            "Program": pid,
            "Type": p.get("program_type") or "-",
            "Lines": p.get("line_count") or 0,
            "Complexity": score,
            "Complexity Label": score_label(score),
            "Is Leaf": "Yes" if is_leaf else "No",
            "Is Entry Point": "Yes" if is_entry else "No",
            "Incoming Calls": incoming,
            "Outgoing Calls": outgoing,
            "Business Name": p.get("business_name") or "-",
            "Suggested Service": _suggest_service(p),
        })

    # Sort by complexity asc (migrate easy ones first), then leaf first
    rows.sort(key=lambda r: (r["Complexity"], -1 if r["Is Leaf"] == "Yes" else 0))

    st.subheader("Migration Order (easiest first)")
    df = pd.DataFrame(rows)
    st.dataframe(df[[
        "Program", "Type", "Lines", "Complexity Label",
        "Is Leaf", "Incoming Calls", "Outgoing Calls",
        "Business Name", "Suggested Service",
    ]], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Complexity Distribution")
    dist = df["Complexity"].value_counts().sort_index()
    st.bar_chart(dist)

    # Summary
    high   = df[df["Complexity"] >= 4]
    medium = df[df["Complexity"] == 3]
    low    = df[df["Complexity"] <= 2]
    leaves = df[df["Is Leaf"] == "Yes"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🟢Low complexity", len(low))
    c2.metric("🟡Medium complexity", len(medium))
    c3.metric("High complexity", len(high))
    c4.metric("Leaf programs (migrate first)", len(leaves))

    st.divider()
    st.subheader("Suggested Microservice Boundaries")
    st.markdown("""
Each module maps to a candidate microservice. Programs within a module share data
structures (copybooks) and call each other — they belong together.
""")
    try:
        loader = db_connect()
        modules = loader.get_all_modules()
        loader.close()
        for m in modules:
            progs  = m.get("programs", [])
            name   = m.get("business_name") or m.get("module_name", "")
            scores = [migration_score(p) for p in progs]
            avg    = sum(scores) / len(scores) if scores else 0
            st.markdown(
                f"**{name}** — {len(progs)} programs, avg complexity {avg:.1f}/5  \n"
                + ", ".join(f"`{p['program_id']}`" for p in progs)
            )
    except Exception:
        st.info("Run pipeline to see module details.")


def _suggest_service(prog: dict) -> str:
    bp = (prog.get("business_purpose") or prog.get("business_name") or "").lower()
    pid = prog.get("program_id", "").upper()
    if any(k in bp for k in ["sign", "auth", "login", "password"]):
        return "auth-service"
    if any(k in bp for k in ["account", "acct"]) or "ACCT" in pid or "ACT" in pid:
        return "account-service"
    if any(k in bp for k in ["transaction", "trxn", "card"]) or "TRN" in pid or "CBT" in pid:
        return "transaction-service"
    if any(k in bp for k in ["user", "usr"]) or "USR" in pid:
        return "user-service"
    if any(k in bp for k in ["report", "statement"]):
        return "reporting-service"
    if any(k in bp for k in ["billing", "payment"]):
        return "billing-service"
    if prog.get("program_type") == "BATCH":
        return "batch-service"
    return "core-service"


# 
# Tab 6: Business Rules
# 

def page_rules():
    st.header("Business Rules Catalog")
    try:
        loader = db_connect()
        rules = loader.get_all_business_rules()
        loader.close()
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    if not rules:
        st.warning("No business rules extracted yet. Run LLM enrichment (enable 'AI Enrichment' in the sidebar and re-run the pipeline).")
        return

    categories = sorted({r.get("category", "GENERAL") for r in rules})
    cat_filter = st.selectbox("Filter by category", ["All"] + categories, key="rules_cat_filter")

    filtered = rules if cat_filter == "All" else [r for r in rules if r.get("category") == cat_filter]
    st.caption(f"Showing {len(filtered)} of {len(rules)} rules")

    for r in filtered:
        with st.expander(f"**{r.get('rule_id','?')}** — {r.get('rule_name','?')} [{r.get('program_id','-')}]"):
            st.markdown(f"**Category:** {r.get('category', '-')}")
            st.markdown(f"**Rule:** {r.get('rule_statement', '-')}")
            st.markdown(f"**When:** {r.get('condition_text') or r.get('condition', '-')}")
            st.markdown(f"**Then:** {r.get('action_text') or r.get('action', '-')}")


# 
# Tab 7: Live Search
# 

def page_search(repo_path):
    st.header("Live Search")
    query = st.text_input("Search programs, data items, rules, or source code")
    if not query:
        return

    tab_docs, tab_code = st.tabs(["Documentation Search", "Source Code Search"])

    with tab_docs:
        try:
            loader = db_connect()
            results = loader.full_text_search(query)
            loader.close()
            progs = results.get("programs", [])
            if progs:
                st.markdown(f"**{len(progs)} programs matched:**")
                for p in progs:
                    st.info(f"**{p['program_id']}** — {p.get('business_name', '')}  \n{(p.get('business_purpose') or '')[:120]}")
            else:
                st.info("No programs matched.")
        except Exception as e:
            st.error(f"Documentation search unavailable: {e}")

    with tab_code:
        matches = search_cobol_files(repo_path, query)
        st.caption(f"{len(matches)} source lines matched")
        for r in matches[:50]:
            with st.expander(f"{r['file']} — Line {r['line']}"):
                st.code(r["content"], language="cobol")


# 
# Tab 8: English Doc Generator (Graph-Aware)
# 

def _fetch_program_subgraph(loader, program_id: str, depth: int) -> list:
    """Walk the call graph up to `depth` hops and return all programs in the subgraph."""
    visited = set()
    frontier = {program_id}

    for _ in range(depth):
        next_frontier = set()
        for pid in frontier:
            if pid in visited:
                continue
            visited.add(pid)
            cg = loader.get_call_graph()
            for edge in cg:
                if edge["caller_program"] == pid and edge.get("called_program") not in ("UNKNOWN", None):
                    next_frontier.add(edge["called_program"])
                if edge["called_program"] == pid:
                    next_frontier.add(edge["caller_program"])
        frontier = next_frontier - visited

    visited.add(program_id)
    all_ids = visited

    programs = []
    for pid in all_ids:
        details = loader.get_program_details(pid)
        if details:
            programs.append(details)
    return programs


def _build_llm_context(programs: list, mode: str, subject: str, loader=None) -> str:
    """Build a rich context string combining enriched English + BMS screens + CICS + JCL for each program."""
    lines = []
    lines.append(f"# COBOL System Documentation Context")
    lines.append(f"Mode: {mode} | Subject: {subject}")
    lines.append(f"Total programs in scope: {len(programs)}\n")
    lines.append("GROUNDING RULES:")
    lines.append("- Use only facts explicitly present in this SYSTEM DATA.")
    lines.append("- Do not infer access technology. If VSAM, DB2, IMS, DL/I, CICS, or JCL is not listed for a program, write \"not present in extracted data\".")
    lines.append("- Copybook names may only come from the Shared Data (Copybooks) line for that program.")
    lines.append("- File and dataset names may only come from Files Accessed or Input/Output Datasets.")
    lines.append("- IMS claims may only come from the IMS DL/I Calls section.\n")

    for prog in programs:
        pid = prog.get("program_id", "?")
        lines.append(f"## Program: {pid}")
        lines.append(f"- Type: {prog.get('program_type', '?')}")
        lines.append(f"- Lines: {prog.get('line_count', 0)}")

        # English enrichment
        bname = prog.get("business_name") or ""
        bpurp = prog.get("business_purpose") or ""
        urole = prog.get("user_role") or ""
        bproc = prog.get("business_process") or ""
        if bname:  lines.append(f"- Business Name: {bname}")
        if bpurp:  lines.append(f"- Purpose: {bpurp}")
        if urole:  lines.append(f"- Triggered by: {urole}")
        if bproc:  lines.append(f"- Business Process: {bproc}")

        # Migration context
        mc = prog.get("migration_complexity")
        me = prog.get("modern_equivalent") or ""
        ss = prog.get("suggested_service") or ""
        ma = prog.get("migration_approach") or ""
        if mc:  lines.append(f"- Migration Complexity: {mc}/5")
        if me:  lines.append(f"- Modern Equivalent: {me}")
        if ss:  lines.append(f"- Target Microservice: {ss}")
        if ma:  lines.append(f"- Migration Approach: {ma}")

        # Dependencies
        calls = [c.get("called_program") for c in (prog.get("calls") or []) if c.get("called_program") not in ("UNKNOWN", None)]
        callers = [c.get("caller_program") for c in (prog.get("called_by") or [])]
        copybooks = [c.get("copybook_name") for c in (prog.get("copybooks") or [])]
        files = [f.get("file_name") for f in (prog.get("files") or [])]
        if loader and not copybooks:
            try:
                cur_copy = loader.conn.cursor()
                cur_copy.execute(
                    "SELECT copybook_name FROM copybook_usage WHERE program_id = ? ORDER BY copybook_name",
                    (pid,),
                )
                copybooks = [r["copybook_name"] for r in cur_copy.fetchall() if r["copybook_name"]]
            except Exception:
                pass
        if calls:     lines.append(f"- Calls: {', '.join(calls)}")
        if callers:   lines.append(f"- Called by: {', '.join(callers)}")
        if copybooks:
            lines.append(f"- Shared Data (Copybooks) — ONLY these copybooks are used by this program: {', '.join(copybooks)}")
        else:
            lines.append("- Shared Data (Copybooks): NONE listed in extracted copybook_usage data.")
        if files:     lines.append(f"- Files Accessed: {', '.join(files)}")

        # Cross-check the physical source so the LLM sees the actual COPY lines,
        # not just derived database rows.
        source_copybooks = []
        source_values = []
        try:
            import re as _re_source
            source_path = prog.get("file_path")
            if source_path and Path(source_path).exists():
                source_text_for_facts = Path(source_path).read_text(encoding="utf-8", errors="ignore")
                source_body_lines = []
                for raw_line in source_text_for_facts.splitlines():
                    if len(raw_line) > 6 and raw_line[6] == "*":
                        continue
                    body = raw_line[6:] if len(raw_line) > 6 else raw_line
                    source_body_lines.append(body[:66] if len(body) > 66 else body)
                source_body = "\n".join(source_body_lines)
                for m in _re_source.finditer(r"\bCOPY\s+([A-Z0-9_-]+)\s*\.", source_body, _re_source.IGNORECASE):
                    cb = m.group(1).upper()
                    if cb not in source_copybooks:
                        source_copybooks.append(cb)
                for name in ("WS-PGMNAME", "WS-INFIL1-STATUS", "WS-INFIL2-STATUS", "PAUT-PCB-STATUS"):
                    m = _re_source.search(
                        rf"\b{name}\b[\s\S]{{0,90}}?\bVALUE\s+['\"]([^'\"]*)['\"]",
                        source_body,
                        _re_source.IGNORECASE,
                    )
                    if m:
                        source_values.append(f"{name} VALUE '{m.group(1)}'")
        except Exception:
            pass
        if source_copybooks:
            lines.append(f"- Source COPY statements (must be documented exactly): {', '.join(source_copybooks)}")
        if source_values:
            lines.append(f"- Source literal/status facts: {', '.join(source_values)}")

        # ── Copybook Field Dictionaries (from copybook_fields table) ─────────
        if loader and copybooks:
            try:
                for cb_name in copybooks[:10]:  # cap copybooks per program
                    cb_fields = loader.get_copybook_fields(cb_name)
                    if not cb_fields:
                        continue
                    lines.append(f"- Copybook `{cb_name}` field dictionary:")
                    for f in cb_fields[:30]:  # cap fields per copybook
                        lvl = f.get("level_number") or ""
                        pic = f.get("picture") or ""
                        usage = f.get("usage") or ""
                        parent = f.get("parent_name") or ""
                        attrs = []
                        if pic:    attrs.append(f"PIC {pic}")
                        if usage:  attrs.append(usage)
                        if f.get("occurs_count"): attrs.append(f"OCCURS {f['occurs_count']}")
                        if f.get("redefines_target"): attrs.append(f"REDEFINES {f['redefines_target']}")
                        attr_str = " ".join(attrs)
                        parent_str = f" (under {parent})" if parent else ""
                        lines.append(f"    {lvl:>02} {f['field_name']:<30} {attr_str}{parent_str}")
                    if len(cb_fields) > 30:
                        lines.append(f"    ... +{len(cb_fields) - 30} more fields")
            except Exception:
                pass

        # ── FD Record Layouts (file contracts) ───────────────────────────────
        if loader:
            try:
                fd_records = loader.get_program_file_records(pid)
                if fd_records:
                    by_file = {}
                    for r in fd_records:
                        by_file.setdefault(r["file_name"], []).append(r)
                    lines.append(f"- File Record Layouts ({len(by_file)} file(s)):")
                    for fname, items in list(by_file.items())[:8]:
                        rec_name = next((it.get("record_name") for it in items if it.get("record_name")), fname)
                        lines.append(f"  FD `{fname}` (record `{rec_name}`):")
                        for it in items[:25]:
                            lvl = it.get("level_number") or ""
                            pic = it.get("picture") or ""
                            usage = it.get("usage") or ""
                            parent = it.get("parent_name") or ""
                            attrs = " ".join(filter(None, [f"PIC {pic}" if pic else "", usage]))
                            parent_str = f" (under {parent})" if parent else ""
                            lines.append(f"    {lvl:>02} {it['field_name']:<30} {attrs}{parent_str}")
                        if len(items) > 25:
                            lines.append(f"    ... +{len(items) - 25} more fields")
            except Exception:
                pass

        # ── Data Movements (lineage: src -> dst) ─────────────────────────────
        if loader:
            try:
                moves = loader.get_program_data_movements(pid, limit=40)
                if moves:
                    lines.append(f"- Data Lineage / MOVE flow ({len(moves)} captured, top entries):")
                    for m in moves[:25]:
                        src = m["source_field"]
                        dst = m["destination_field"]
                        para = m.get("paragraph_name") or "?"
                        line = m.get("line_number") or "?"
                        if m.get("is_literal"):
                            lines.append(f"    '{src}' -> {dst}   [{para}:L{line}]")
                        else:
                            lines.append(f"    {src} -> {dst}   [{para}:L{line}]")
                    if len(moves) > 25:
                        lines.append(f"    ... +{len(moves) - 25} more movements")
            except Exception:
                pass

        # ── CICS Commands ────────────────────────────────────────────────────
        if loader:
            try:
                cics_stmts = loader.get_program_statements(pid, "EXEC_CICS")
                if cics_stmts:
                    lines.append(f"- CICS Commands ({len(cics_stmts)} total):")
                    for cs in cics_stmts[:15]:
                        import json as _json
                        try:
                            det = _json.loads(cs.get("details_json") or "{}")
                        except Exception:
                            det = {}
                        cmd = det.get("cics_command", "UNKNOWN")
                        details = det.get("details", {})
                        detail_str = ", ".join(f"{k}={v}" for k, v in details.items()) if details else ""
                        para = cs.get("paragraph_name", "")
                        line = cs.get("line_number", "")
                        entry = f"EXEC CICS {cmd}"
                        if detail_str:
                            entry += f" ({detail_str})"
                        if para:
                            entry += f" [in {para}, line {line}]"
                        lines.append(f"  * {entry}")
            except Exception:
                pass

        # ── EXEC SQL (DB2) ───────────────────────────────────────────────────
        if loader:
            try:
                cur_sql = loader.conn.cursor()
                cur_sql.execute("""
                    SELECT command, table_name, cursor_name, paragraph_name, line_number
                    FROM exec_sql WHERE program_id = ? ORDER BY line_number
                """, (pid,))
                sql_rows = [dict(r) for r in cur_sql.fetchall()]
                if sql_rows:
                    lines.append(f"- SQL/DB2 Operations ({len(sql_rows)} total):")
                    for s in sql_rows[:15]:
                        cmd = s.get("command", "?")
                        tbl = s.get("table_name") or s.get("cursor_name") or "-"
                        para = s.get("paragraph_name", "")
                        line = s.get("line_number", "")
                        suffix = f" [in {para}, line {line}]" if para else ""
                        lines.append(f"  * EXEC SQL {cmd} on {tbl}{suffix}")
            except Exception:
                pass

        # ── BMS Screen Layout ────────────────────────────────────────────────
        if loader:
            try:
                cursor = loader.conn.cursor()
                cursor.execute("""
                    SELECT s.id, s.screen_name, s.map_name, s.mapset_name, s.business_name
                    FROM screens s
                    WHERE s.associated_program = ?
                """, (pid,))
                screens = [dict(r) for r in cursor.fetchall()]
                if screens:
                    lines.append(f"- BMS Screens ({len(screens)} maps):")
                    for scr in screens[:5]:
                        sname = scr.get("screen_name", "")
                        mapset = scr.get("mapset_name", "")
                        sbname = scr.get("business_name") or ""
                        lines.append(f"  * Screen: {sname} (mapset: {mapset})" + (f" — {sbname}" if sbname else ""))
                        # Get fields
                        cursor.execute("""
                            SELECT field_name, field_type, length, row_position, col_position, attributes
                            FROM screen_fields
                            WHERE screen_id = ? AND field_name NOT LIKE '\\_LABEL%' ESCAPE '\\'
                            ORDER BY row_position, col_position
                        """, (scr["id"],))
                        fields = [dict(r) for r in cursor.fetchall()]
                        if fields:
                            input_fields = [f for f in fields if f["field_type"] == "INPUT"]
                            output_fields = [f for f in fields if f["field_type"] == "OUTPUT"]
                            if input_fields:
                                lines.append(f"    Input Fields: {', '.join(f['field_name'] + '(' + str(f['length']) + ')' for f in input_fields[:12])}")
                            if output_fields:
                                lines.append(f"    Output Fields: {', '.join(f['field_name'] + '(' + str(f['length']) + ')' for f in output_fields[:12])}")
                            lines.append(f"    Total fields: {len(fields)} ({len(input_fields)} input, {len(output_fields)} output)")
            except Exception:
                pass

        # ── JCL Job Context ──────────────────────────────────────────────────
        if loader:
            try:
                jcl_jobs = loader.get_program_jcl_jobs(pid)
                if jcl_jobs:
                    lines.append(f"- JCL Execution Context ({len(jcl_jobs)} job steps):")
                    seen_jobs = set()
                    for j in jcl_jobs[:8]:
                        jname = j.get("job_name", "")
                        step = j.get("step_name", "")
                        desc = j.get("job_description", "")
                        comment = j.get("step_comments", "")
                        entry = f"Job {jname}, Step {step}"
                        if desc:
                            entry += f" — {desc}"
                        lines.append(f"  * {entry}")
                        if comment and jname not in seen_jobs:
                            lines.append(f"    Step purpose: {comment[:150]}")
                        seen_jobs.add(jname)
                        # Get datasets for this job/step
                        if jname not in seen_jobs or len(seen_jobs) <= 3:
                            try:
                                job_detail = loader.get_jcl_job_details(jname)
                                if job_detail:
                                    in_ds = job_detail.get("input_datasets", [])
                                    out_ds = job_detail.get("output_datasets", [])
                                    if in_ds:
                                        lines.append(f"    Input datasets: {', '.join(str(d) for d in in_ds[:5])}")
                                    if out_ds:
                                        lines.append(f"    Output datasets: {', '.join(str(d) for d in out_ds[:5])}")
                            except Exception:
                                pass
                    # ── JCL SYSIN Content ─────────────────────────────────────
                    try:
                        import json as _json_sysin
                        cur_sysin = loader.conn.cursor()
                        cur_sysin.execute("""
                            SELECT step_name, sysin_data FROM jcl_steps
                            WHERE UPPER(program) = UPPER(?) AND sysin_data IS NOT NULL
                            ORDER BY step_order
                        """, (pid,))
                        for sr in cur_sysin.fetchall():
                            sysin_raw = sr["sysin_data"]
                            if not sysin_raw:
                                continue
                            try:
                                sysin_lines = _json_sysin.loads(sysin_raw)
                                if isinstance(sysin_lines, list) and sysin_lines:
                                    lines.append(f"  * SYSIN content for step {sr['step_name']}:")
                                    for sl in sysin_lines[:20]:
                                        lines.append(f"    {sl}")
                            except Exception:
                                # sysin_data might be plain text
                                if sysin_raw.strip():
                                    lines.append(f"  * SYSIN content for step {sr['step_name']}:")
                                    for sl in sysin_raw.strip().split('\n')[:20]:
                                        lines.append(f"    {sl}")
                    except Exception:
                        pass
            except Exception:
                pass

        # ── IMS DL/I Calls ────────────────────────────────────────────────────
        if loader:
            try:
                cur_ims = loader.conn.cursor()
                cur_ims.execute("""
                    SELECT function_code, function_name, pcb_name, segment_area,
                           ssa_name, ssa_segment, ssa_qualifier, paragraph_name, line_number
                    FROM ims_calls WHERE program_id = ? ORDER BY line_number
                """, (pid,))
                ims_rows = [dict(r) for r in cur_ims.fetchall()]
                if ims_rows:
                    lines.append(f"- IMS DL/I Calls ({len(ims_rows)} total):")
                    for im in ims_rows[:20]:
                        fn = im.get("function_code", "?")
                        fn_name = im.get("function_name", "")
                        pcb = im.get("pcb_name", "")
                        area = im.get("segment_area", "")
                        ssa = im.get("ssa_name", "")
                        seg = im.get("ssa_segment", "")
                        qual = im.get("ssa_qualifier", "")
                        para = im.get("paragraph_name", "")
                        lno = im.get("line_number", "")
                        entry = f"CALL 'CBLTDLI' {fn}"
                        if fn_name:
                            entry += f" ({fn_name})"
                        if pcb:
                            entry += f" PCB={pcb}"
                        if area:
                            entry += f", Area={area}"
                        if ssa:
                            entry += f", SSA={ssa}"
                        if seg:
                            entry += f" (segment: {seg})"
                        if qual:
                            entry += f", qualifier: {qual}"
                        if para:
                            entry += f" [in {para}, line {lno}]"
                        lines.append(f"  * {entry}")
                    ssa_rows = [im for im in ims_rows if im.get("ssa_name")]
                    if ssa_rows:
                        lines.append("  SSA structures that must be explained:")
                        seen_ssas = set()
                        for im in ssa_rows:
                            ssa = im.get("ssa_name", "")
                            if not ssa or ssa in seen_ssas:
                                continue
                            seen_ssas.add(ssa)
                            seg = im.get("ssa_segment") or "(segment not present in extracted data)"
                            qual = im.get("ssa_qualifier") or "(no qualifier present in extracted data)"
                            lines.append(f"    - {ssa}: segment={seg}; qualifier={qual}")
                    if any(im.get("function_code") == "ENTRY" for im in ims_rows):
                        lines.append("  IMS entry point: ENTRY 'DLITCBL' is present and must be documented as the IMS batch entry point.")
            except Exception:
                pass

        # Paragraph names (always include — required for citation enforcement)
        paras = prog.get("paragraphs") or []
        if paras:
            lines.append(f"- Paragraphs ({len(paras)} total — cite by exact name):")
            for p in paras[:25]:
                pname = p.get("paragraph_name", "")
                if not pname:
                    continue
                bname_p = p.get("business_name") or ""
                narr = p.get("narrative") or p.get("purpose") or ""
                line_start = p.get("line_start") or ""
                # Always show the exact paragraph name; append narrative/business name if present
                detail = ""
                if narr:
                    detail = f" — {narr[:150]}"
                elif bname_p and bname_p != pname:
                    detail = f" ({bname_p})"
                line_suffix = f" [line {line_start}]" if line_start else ""
                lines.append(f"  * `{pname}`{line_suffix}{detail}")
            if len(paras) > 25:
                lines.append(f"  ... and {len(paras) - 25} more paragraphs")

        # IMS programs need source-grounded paragraph bodies; otherwise the LLM
        # tends to infer DL/I behavior from names alone.
        try:
            from pathlib import Path as _Path
            source_path = prog.get("file_path")
            ims_rows_for_source = prog.get("ims_calls") or []
            source_text = ""
            if source_path and _Path(source_path).exists():
                source_text = _Path(source_path).read_text(encoding="utf-8", errors="ignore")
            if paras and source_text and (ims_rows_for_source or "CBLTDLI" in source_text.upper() or "DLITCBL" in source_text.upper()):
                source_lines = source_text.splitlines()

                def _cobol_body(raw_line: str) -> str:
                    if len(raw_line) > 6 and raw_line[6] == "*":
                        return ""
                    body = raw_line[6:] if len(raw_line) > 6 else raw_line
                    return (body[:66] if len(body) > 66 else body).rstrip()

                import re as _re_para
                para_names = [p.get("paragraph_name", "").upper() for p in paras if p.get("paragraph_name")]
                starts = []
                for idx, raw in enumerate(source_lines, 1):
                    body = _cobol_body(raw).strip().upper()
                    for para_name in para_names:
                        if _re_para.match(rf"^{_re_para.escape(para_name)}\s*\.", body):
                            starts.append((idx, para_name))
                            break
                starts.sort()
                source_ranges = {}
                for pos, (start, para_name) in enumerate(starts):
                    end = starts[pos + 1][0] - 1 if pos + 1 < len(starts) else len(source_lines)
                    source_ranges[para_name] = (start, end)

                lines.append("- IMS Paragraph Source Snippets (first 50 body lines per paragraph):")
                for p in paras:
                    pname = p.get("paragraph_name", "")
                    start, end = source_ranges.get(pname.upper(), (p.get("line_start") or 0, p.get("line_end") or p.get("line_start") or 0))
                    if not pname or not start:
                        continue
                    snippet = []
                    for raw in source_lines[start - 1:min(end, start + 49, len(source_lines))]:
                        body = _cobol_body(raw)
                        if body.strip():
                            snippet.append(body)
                    if snippet:
                        lines.append(f"  Paragraph `{pname}`:")
                        for body in snippet:
                            lines.append(f"    {body}")
        except Exception:
            pass

        # Business rules
        rules = prog.get("business_rules") or []
        if rules:
            lines.append(f"- Business Rules ({len(rules)} total):")
            for r in rules[:5]:
                rs = r.get("rule_statement") or r.get("description") or ""
                if rs:
                    lines.append(f"  * {rs[:150]}")

        lines.append("")

    return "\n".join(lines)


def _call_vertex_for_doc(context: str, mode: str, subject: str) -> str:
    """Send context to Vertex AI Gemini and return a full English narrative document."""
    try:
        from langchain_google_vertexai import ChatVertexAI
        from langchain_core.messages import HumanMessage

        project = os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("VERTEX_LOCATION", "us-central1")
        model_name = os.environ.get("VERTEX_MODEL", "gemini-2.5-flash")
        # gemini-2.0-flash caps max_output_tokens at 8192; 2.5-flash allows 65536.
        max_tokens = int(os.environ.get(
            "VERTEX_MAX_OUTPUT_TOKENS",
            "8192" if "2.0" in model_name else "65536",
        ))

        model = ChatVertexAI(
            model_name=model_name,
            project=project,
            location=location,
            temperature=0.3,
            max_output_tokens=max_tokens,
        )

        grounding_rules = """GROUNDING RULES:
- Do NOT infer access technology. If SYSTEM DATA does not explicitly state the program uses VSAM, DB2, IMS, DL/I, CICS, or JCL, do not claim it does.
- Copybook names: only reference copybooks that appear verbatim in "Shared Data (Copybooks)" in SYSTEM DATA. Never substitute or invent names.
- If "Shared Data (Copybooks)" or "Source COPY statements" lists copybooks, never write that the program has no COPY statements or no copybooks.
- File and dataset names: only reference names that appear in "Files Accessed" or "Input/Output Datasets" in SYSTEM DATA.
- IMS DL/I calls: only reference IMS functions that appear in the "IMS DL/I Calls" section of SYSTEM DATA. Do not infer IMS usage.
- For IMS programs, document ENTRY 'DLITCBL' when present, each CBLTDLI function, PCB, segment area, SSA name, segment, qualifier, exact paragraph, and PCB status handling.
- Business rules must be tied to exact source conditions and actions from SYSTEM DATA rather than generic summaries.
- If a fact is missing from SYSTEM DATA, write "(not present in extracted data)" rather than guessing.
"""

        if mode == "Program":
            prompt = f"""You are a senior software architect documenting a legacy COBOL system for migration to modern services.

Using the structured data below, write a comprehensive technical documentation document for the program "{subject}" and all its connected programs.

The document must:
1. Start with an Executive Summary — what this program does in plain English, who triggers it, and its business importance
2. Explain each program in the dependency chain in order of execution flow — not alphabetically
3. For each program: explain what it does, what data it reads/writes, what business decisions it makes, and what it produces
4. Describe how the programs connect — which calls which, what data flows between them, what shared data structures exist
5. Highlight any critical business rules or validation logic
6. If the program is ONLINE (CICS): describe the BMS screen layout — what fields the user sees, what they can input, what gets displayed. Describe the CICS commands used (SEND MAP, RECEIVE MAP, READ, WRITE, XCTL, LINK, RETURN) and how they form the screen interaction flow
7. If the program runs via JCL: describe the batch job context — job name, execution steps, input/output datasets, and how this program fits into the batch processing chain
8. End with a Migration Notes section — complexity, suggested modern equivalent, recommended microservice boundary. For CICS programs, suggest REST API + modern UI replacement. For batch programs, suggest cloud-native batch or event-driven alternatives

Write as proper technical documentation — clear headings, flowing prose, specific details. Avoid generic statements.

{grounding_rules}

SYSTEM DATA:
{context}

Write the documentation now:"""

        elif mode == "Module":
            prompt = f"""You are a senior software architect documenting a legacy COBOL system for migration to modern microservices.

Using the structured data below, write a comprehensive module specification document for the "{subject}" module.

The document must:
1. Start with a Module Overview — what business capability this module provides, who uses it, and its role in the overall system
2. List all programs in this module with their individual purposes
3. Explain the internal flow — how programs within this module interact, the sequence of operations
4. Describe the data architecture — what files, datasets, and shared copybooks this module uses
5. For ONLINE programs: describe the BMS screen layouts (input/output fields, screen flow), CICS commands used, and the user interaction pattern (SEND MAP → user input → RECEIVE MAP → process → respond)
6. For batch programs: describe the JCL job execution context — which jobs run the program, what datasets flow in/out, execution sequence and dependencies
7. Document all key business rules and validations enforced by this module
8. Describe external dependencies — what other modules/programs this module depends on or is depended upon by
9. End with a Migration Strategy — recommended service boundary, suggested modern architecture (REST APIs for CICS screens, cloud batch for JCL jobs), migration order for programs within this module

Write as a proper software specification — clear sections, numbered headings, specific technical details, flowing explanations.

{grounding_rules}

SYSTEM DATA:
{context}

Write the module specification now:"""

        else:  # Application mode
            prompt = f"""You are a chief software architect producing the definitive architecture document for an entire legacy COBOL mainframe application, to hand off to a modernisation team.

Using the structured data below covering ALL programs, modules, call relationships and business rules in the system, write a comprehensive Application Architecture Document.

CRITICAL FORMATTING RULES:
- Do NOT use markdown tables anywhere in this document. Use numbered lists and prose instead.
- Each section must be complete. Do not truncate or summarise prematurely.
- Write every module subsection in full — do not skip any module.

The document must contain these numbered sections:

1. Executive Summary
   What this entire application does, who uses it, its business criticality, and the case for modernisation. 2-3 paragraphs.

2. System Architecture Overview
   How the online (CICS) tier and batch tier work together. Entry points, schedulers, user touchpoints. Describe the two-tier architecture in prose.

3. Module Breakdown
   One numbered subsection per module. For each module write:
   - Business domain and purpose
   - List of programs with one-sentence role for each
   - How programs within the module interact internally

4. CICS Online Tier & BMS Screens
   Describe the online (CICS) programs and their associated BMS screen maps. For each screen: what fields the user sees, the interaction flow (SEND MAP → input → RECEIVE MAP → process), and what CICS commands drive the screen navigation. Explain how XCTL and LINK route between screens.

5. Batch Processing Tier & JCL Jobs
   Describe the JCL batch jobs: what each job does, which programs it executes, what datasets flow in and out, and the batch execution schedule/dependencies. Explain how batch and online tiers interact (e.g., batch jobs processing transactions queued by online programs).

6. Inter-Module Data Flow
   Which modules depend on which other modules. Shared files and copybooks that couple modules together. The three or four most critical data paths through the system described as step-by-step flows.

7. Business Rule Inventory
   The rule categories, how many rules exist in each category, and which modules carry the highest rule density. Identify the top 5 programs by rule count and describe what kinds of rules they contain.

8. Migration Roadmap
   For EACH module, write a numbered subsection containing:
   - Recommended target microservice name
   - For CICS screens: suggest REST API + modern UI (React/Angular) replacement
   - For batch JCL: suggest cloud-native batch (AWS Batch, Step Functions) or event-driven alternatives
   - Migration order (1 = migrate first, higher = migrate later) with justification
   - Key technical risks for this module
   - Suggested modern technology stack

   After all modules, write a recommended overall migration sequence as a numbered ordered list.

9. Risk Register
   The top 7 highest-risk components as a numbered list. For each: the program or module name, why it is high risk (coupling, size, MQ dependencies, unknown purpose), and a concrete mitigation strategy.

{grounding_rules}

SYSTEM DATA:
{context}

Write the full Architecture Document now. Do not truncate any section:"""

        response = model.invoke([HumanMessage(content=prompt)])
        return response.content

    except Exception as e:
        return f"Error generating documentation: {e}"

def _markdown_to_pdf(markdown_text: str, title: str) -> bytes:
    """Convert Markdown text to PDF bytes using reportlab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from doc_agent_pipeline import run_doc_pipeline

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=inch, leftMargin=inch,
        topMargin=inch, bottomMargin=inch,
        title=title,
    )

    styles = getSampleStyleSheet()
    style_h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, spaceAfter=12, textColor=colors.HexColor("#1a1a2e"))
    style_h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14, spaceAfter=8, spaceBefore=16, textColor=colors.HexColor("#16213e"))
    style_h3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=12, spaceAfter=6, spaceBefore=10, textColor=colors.HexColor("#0f3460"))
    style_body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, spaceAfter=6, leading=14)
    style_bullet = ParagraphStyle("Bullet", parent=styles["Normal"], fontSize=10, leftIndent=20, spaceAfter=4, bulletIndent=10)
    style_code = ParagraphStyle("Code", parent=styles["Code"], fontSize=8, backColor=colors.HexColor("#f4f4f4"), spaceAfter=6, leading=12)

    story = []

    for line in markdown_text.split("\n"):
        line_stripped = line.strip()
        if not line_stripped:
            story.append(Spacer(1, 6))
            continue

        # Escape XML special chars
        safe = line_stripped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if line_stripped.startswith("# "):
            story.append(Paragraph(safe[2:], style_h1))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a1a2e")))
        elif line_stripped.startswith("## "):
            story.append(Paragraph(safe[3:], style_h2))
        elif line_stripped.startswith("### "):
            story.append(Paragraph(safe[4:], style_h3))
        elif line_stripped.startswith("- ") or line_stripped.startswith("* "):
            story.append(Paragraph(f"• {safe[2:]}", style_bullet))
        elif line_stripped.startswith("  * ") or line_stripped.startswith("  - "):
            story.append(Paragraph(f"   {safe[4:]}", style_bullet))
        elif line_stripped.startswith("`") and line_stripped.endswith("`"):
            story.append(Paragraph(safe[1:-1], style_code))
        elif line_stripped.startswith("**") and line_stripped.endswith("**"):
            story.append(Paragraph(f"<b>{safe[2:-2]}</b>", style_body))
        else:
            # Handle inline bold
            import re
            formatted = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)
            formatted = re.sub(r'\*(.+?)\*', r'<i>\1</i>', formatted)
            story.append(Paragraph(formatted, style_body))

    doc.build(story)
    return buffer.getvalue()

def _fetch_application_subgraph(loader) -> dict:
    """
    Fetch system-wide data for application-level documentation.
    Trims heavy per-program fields to keep LLM context manageable.
    """
    programs     = loader.get_all_programs()
    modules      = loader.get_all_modules()
    call_graph   = loader.get_call_graph()
    rules        = loader.get_all_business_rules()
    screens      = loader.get_all_screens()
    try:
        jcl_cursor = loader.conn.cursor()
        jcl_cursor.execute("SELECT job_name, job_description, step_count, programs_called, input_datasets, output_datasets FROM jcl_jobs")
        jcl_jobs = [dict(r) for r in jcl_cursor.fetchall()]
    except Exception:
        jcl_jobs = []

    # CICS command summary per program
    try:
        cics_cursor = loader.conn.cursor()
        cics_cursor.execute("""
            SELECT program_id, command, COUNT(*) as cnt
            FROM exec_cics
            GROUP BY program_id, command
            ORDER BY program_id, cnt DESC
        """)
        cics_rows = [dict(r) for r in cics_cursor.fetchall()]
    except Exception:
        cics_rows = []

    # SQL summary per program + per table
    try:
        sql_cursor = loader.conn.cursor()
        sql_cursor.execute("""
            SELECT program_id, command, table_name, COUNT(*) as cnt
            FROM exec_sql
            GROUP BY program_id, command, table_name
            ORDER BY program_id
        """)
        sql_rows = [dict(r) for r in sql_cursor.fetchall()]
    except Exception:
        sql_rows = []

    program_details = []
    for prog in programs:
        details = loader.get_program_details(prog["program_id"])
        if details:
            # Drop high-volume fields that don't add value at system level
            details.pop("statements", None)
            details.pop("data_items", None)
            program_details.append(details)

    return {
        "programs": program_details,
        "modules": modules,
        "call_graph": call_graph,
        "rules": rules,
        "screens": screens,
        "jcl_jobs": jcl_jobs,
        "cics_rows": cics_rows,
        "sql_rows": sql_rows,
        "stats": {
            "total_programs": len(programs),
            "total_modules": len(modules),
            "total_calls": len(call_graph),
            "total_rules": len(rules),
            "total_screens": len(screens),
            "total_jcl_jobs": len(jcl_jobs),
            "total_cics_commands": sum(r.get("cnt", 0) for r in cics_rows),
            "total_cics_programs": len({r["program_id"] for r in cics_rows}),
            "total_sql_statements": sum(r.get("cnt", 0) for r in sql_rows),
            "total_sql_programs": len({r["program_id"] for r in sql_rows}),
            "total_sql_tables": len({r["table_name"] for r in sql_rows if r.get("table_name")}),
        },
    }


def _build_application_llm_context(data: dict) -> str:
    """Build a compact but rich context string for the entire application."""
    import json as _json
    from collections import Counter
    stats = data["stats"]
    lines = [
        "# COBOL Application — System-Wide Context",
        f"Programs: {stats['total_programs']} | Modules: {stats['total_modules']} "
        f"| Call Relationships: {stats['total_calls']} | Business Rules: {stats['total_rules']} "
        f"| BMS Screens: {stats.get('total_screens', 0)} | JCL Jobs: {stats.get('total_jcl_jobs', 0)} "
        f"| CICS Commands: {stats.get('total_cics_commands', 0)} across {stats.get('total_cics_programs', 0)} programs "
        f"| SQL Statements: {stats.get('total_sql_statements', 0)} across {stats.get('total_sql_programs', 0)} programs "
        f"using {stats.get('total_sql_tables', 0)} tables",
        "",
    ]

    # Module breakdown
    lines.append("## Module Structure")
    for m in data["modules"]:
        name  = m.get("business_name") or m.get("module_name", "")
        progs = m.get("programs", [])
        lines.append(f"\n### {name} ({len(progs)} programs)")
        lines.append("Programs: " + ", ".join(p["program_id"] for p in progs))
        for p in progs:
            if p.get("business_purpose"):
                lines.append(f"  - {p['program_id']}: {p['business_purpose'][:120]}")

    # Call graph (top 60 edges)
    lines.append("\n## Key Call Relationships")
    for call in data["call_graph"][:60]:
        if call.get("called_program") not in ("UNKNOWN", None):
            lines.append(f"- {call['caller_program']} -> {call['called_program']}")

    # ── BMS Screen Summary ───────────────────────────────────────────────────
    app_screens = data.get("screens", [])
    if app_screens:
        lines.append(f"\n## BMS Screen Maps ({len(app_screens)} screens)")
        for scr in app_screens[:30]:
            sname = scr.get("screen_name", "")
            mapset = scr.get("mapset_name", "")
            assoc = scr.get("associated_program") or "unlinked"
            field_names = scr.get("field_names", "") or ""
            lines.append(f"- {sname} (mapset: {mapset}, program: {assoc})")
            if field_names:
                lines.append(f"  Fields: {field_names[:200]}")

    # ── JCL Jobs Summary ─────────────────────────────────────────────────────
    app_jcl = data.get("jcl_jobs", [])
    if app_jcl:
        lines.append(f"\n## JCL Batch Jobs ({len(app_jcl)} jobs)")
        for j in app_jcl[:30]:
            jname = j.get("job_name", "")
            desc = j.get("job_description", "")
            steps = j.get("step_count", 0)
            try:
                progs_called = _json.loads(j.get("programs_called") or "[]")
            except Exception:
                progs_called = []
            try:
                in_ds = _json.loads(j.get("input_datasets") or "[]")
            except Exception:
                in_ds = []
            try:
                out_ds = _json.loads(j.get("output_datasets") or "[]")
            except Exception:
                out_ds = []
            entry = f"- {jname} ({steps} steps)"
            if desc:
                entry += f" — {desc}"
            lines.append(entry)
            if progs_called:
                lines.append(f"  Executes: {', '.join(str(p) for p in progs_called[:8])}")
            if in_ds:
                lines.append(f"  Reads: {', '.join(str(d) for d in in_ds[:5])}")
            if out_ds:
                lines.append(f"  Writes: {', '.join(str(d) for d in out_ds[:5])}")

    # ── CICS Command Summary ─────────────────────────────────────────────────
    cics_rows = data.get("cics_rows", [])
    if cics_rows:
        # Group by program
        from collections import defaultdict
        by_program = defaultdict(list)
        for r in cics_rows:
            by_program[r["program_id"]].append((r["command"], r["cnt"]))

        # Overall command-type histogram
        cmd_totals = Counter()
        for r in cics_rows:
            cmd_totals[r["command"]] += r["cnt"]

        lines.append(
            f"\n## CICS Command Usage "
            f"({stats.get('total_cics_commands', 0)} commands across "
            f"{stats.get('total_cics_programs', 0)} programs)"
        )
        lines.append("\n### Command Types Across the Application")
        for cmd, cnt in cmd_totals.most_common():
            lines.append(f"- {cmd}: {cnt}")

        lines.append("\n### Top CICS-Using Programs")
        prog_totals = sorted(
            ((pid, sum(cnt for _, cnt in cmds)) for pid, cmds in by_program.items()),
            key=lambda x: -x[1],
        )
        for pid, total in prog_totals[:15]:
            cmds = by_program[pid]
            cmd_str = ", ".join(f"{c}({n})" for c, n in cmds)
            lines.append(f"- {pid}: {total} commands — {cmd_str}")

    # ── SQL/DB2 Summary ──────────────────────────────────────────────────────
    sql_rows = data.get("sql_rows", [])
    if sql_rows:
        from collections import defaultdict
        sql_by_program = defaultdict(list)
        for r in sql_rows:
            sql_by_program[r["program_id"]].append((r["command"], r.get("table_name"), r["cnt"]))

        sql_cmd_totals = Counter()
        sql_table_totals = Counter()
        for r in sql_rows:
            sql_cmd_totals[r["command"]] += r["cnt"]
            if r.get("table_name"):
                sql_table_totals[r["table_name"]] += r["cnt"]

        lines.append(
            f"\n## SQL/DB2 Usage "
            f"({stats.get('total_sql_statements', 0)} statements across "
            f"{stats.get('total_sql_programs', 0)} programs, "
            f"{stats.get('total_sql_tables', 0)} tables)"
        )
        lines.append("\n### SQL Command Mix")
        for cmd, cnt in sql_cmd_totals.most_common():
            lines.append(f"- {cmd}: {cnt}")

        lines.append("\n### Most Accessed Tables")
        for tbl, cnt in sql_table_totals.most_common(15):
            lines.append(f"- {tbl}: {cnt} accesses")

        lines.append("\n### Top SQL-Using Programs")
        prog_totals = sorted(
            ((pid, sum(cnt for _, _, cnt in ops)) for pid, ops in sql_by_program.items()),
            key=lambda x: -x[1],
        )
        for pid, total in prog_totals[:10]:
            ops = sql_by_program[pid]
            tables_touched = sorted({t for _, t, _ in ops if t})
            tbl_str = ", ".join(tables_touched[:4]) + (" ..." if len(tables_touched) > 4 else "")
            lines.append(f"- {pid}: {total} statements, tables: {tbl_str or '(no FROM clause detected)'}")

    # Business rule category summary
    lines.append(f"\n## Business Rule Categories ({stats['total_rules']} rules)")
    cats = Counter(r.get("category", "GENERAL") for r in data["rules"])
    for cat, count in cats.most_common():
        lines.append(f"- {cat}: {count} rules")

    # Per-program detail (enriched metadata only)
    lines.append("\n## Program Details")
    for prog in data["programs"]:
        pid = prog.get("program_id", "?")
        lines.append(f"\n### {pid}")
        for field, label in [
            ("business_name",    "Business Name"),
            ("business_purpose", "Purpose"),
            ("program_type",     "Type"),
            ("line_count",       "Lines"),
            ("suggested_service","Target Service"),
            ("migration_complexity", "Migration Complexity"),
            ("modern_equivalent",    "Modern Equivalent"),
        ]:
            val = prog.get(field)
            if val:
                val_str = str(val)[:150] if field == "business_purpose" else str(val)
                lines.append(f"- {label}: {val_str}")
        calls_out = [
            c.get("called_program") for c in (prog.get("calls") or [])
            if c.get("called_program") not in ("UNKNOWN", None)
        ]
        if calls_out:
            lines.append(f"- Calls: {', '.join(calls_out)}")
        paras = prog.get("paragraphs") or []
        if paras:
            lines.append(f"- Key Functions: " + " | ".join(
                p.get("business_name") or p.get("paragraph_name", "") for p in paras[:6]
            ))

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Simple Diagrams for Doc Generator (deterministic, no LLM)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_mermaid_id(s: str) -> str:
    """Sanitise a string for use as a Mermaid node ID — only alnum + underscore."""
    import re as _re
    return _re.sub(r"[^A-Za-z0-9_]", "_", s)


def _build_program_call_diagram(loader, program_id: str, depth: int = 1) -> str:
    """Program-centric flowchart: COBOL CALLs + CICS XCTL/LINK + JCL parents +
    shared-copybook coupling. Falls back gracefully when CALL relationships are absent."""
    import json as _json
    cur = loader.conn.cursor()

    # COBOL CALLs
    cg = loader.get_call_graph()
    callers = [e["caller_program"] for e in cg
               if e["called_program"] == program_id]
    callees = [e["called_program"] for e in cg
               if e["caller_program"] == program_id
               and e.get("called_program") not in ("UNKNOWN", None)]

    # CICS XCTL/LINK transfers
    cics_targets = []
    try:
        cur.execute("""
            SELECT command, details_json FROM exec_cics
            WHERE program_id = ? AND command IN ('XCTL','LINK')
        """, (program_id,))
        for r in cur.fetchall():
            try:
                d = _json.loads(r["details_json"] or "{}")
                inner = d.get("details", d) or {}
                tgt = inner.get("program")
                if tgt:
                    cics_targets.append((r["command"], tgt))
            except Exception:
                pass
    except Exception:
        pass

    # JCL parent jobs
    jcl_jobs = []
    try:
        cur.execute("SELECT DISTINCT job_name FROM jcl_steps WHERE program = ?", (program_id,))
        jcl_jobs = [r["job_name"] for r in cur.fetchall()]
    except Exception:
        pass

    # Programs sharing copybooks with this one
    copy_partners = []
    try:
        cur.execute("""
            SELECT cu2.program_id AS partner, GROUP_CONCAT(cu2.copybook_name) AS cbs
            FROM copybook_usage cu1
            JOIN copybook_usage cu2 ON cu1.copybook_name = cu2.copybook_name
            WHERE cu1.program_id = ? AND cu2.program_id != ?
            GROUP BY cu2.program_id
            ORDER BY COUNT(*) DESC
            LIMIT 6
        """, (program_id, program_id))
        copy_partners = [(r["partner"], r["cbs"]) for r in cur.fetchall()]
    except Exception:
        pass

    lines = ["flowchart LR"]
    sid = _safe_mermaid_id(program_id)
    lines.append(f'    {sid}["{program_id}"]:::focus')

    # JCL parents (above)
    for j in jcl_jobs[:8]:
        jid = "JCL_" + _safe_mermaid_id(j)
        lines.append(f'    {jid}[/"{j}.jcl"/]:::jcl')
        lines.append(f"    {jid} ==> {sid}")

    # COBOL callers
    for c in callers[:15]:
        cid = _safe_mermaid_id(c)
        lines.append(f'    {cid}["{c}"]:::caller')
        lines.append(f"    {cid} --> {sid}")

    # COBOL callees
    for c in callees[:15]:
        cid = _safe_mermaid_id(c)
        lines.append(f'    {cid}["{c}"]:::callee')
        lines.append(f"    {sid} --> {cid}")

    # CICS XCTL/LINK
    for cmd, tgt in cics_targets[:10]:
        tid = _safe_mermaid_id(tgt)
        lines.append(f'    {tid}["{tgt}"]:::cics')
        lines.append(f"    {sid} -->|CICS {cmd}| {tid}")

    # Shared copybook partners (dashed, with copybook name as label)
    for partner, cbs in copy_partners:
        pid = _safe_mermaid_id(partner)
        cb_label = cbs.split(",")[0] if cbs else "shared"
        more = "" if (cbs or "").count(",") == 0 else f" +{cbs.count(',')}"
        lines.append(f'    {pid}["{partner}"]:::partner')
        lines.append(f'    {sid} -..->|"{cb_label}{more}"| {pid}')

    lines.append("    classDef focus fill:#388bfd,stroke:#58a6ff,color:#fff,stroke-width:2px")
    lines.append("    classDef caller fill:#f0883e,stroke:#db6d28,color:#fff")
    lines.append("    classDef callee fill:#2ea043,stroke:#3fb950,color:#fff")
    lines.append("    classDef cics fill:#a371f7,stroke:#bc8cff,color:#fff")
    lines.append("    classDef jcl fill:#d29922,stroke:#9e6a03,color:#fff")
    lines.append("    classDef partner fill:#30363d,stroke:#6e7681,color:#c9d1d9")
    return "\n".join(lines)


def _build_module_diagram(loader, module) -> str:
    """Module flowchart: COBOL CALLs + CICS XCTL/LINK + JCL parents +
    shared-copybook coupling between module programs."""
    import json as _json
    progs = module.get("programs", [])
    prog_ids = {p["program_id"] for p in progs}
    if not prog_ids:
        return "flowchart TD\n    empty[\"No programs in module\"]"

    cg = loader.get_call_graph()
    cur = loader.conn.cursor()
    placeholders = ",".join("?" * len(prog_ids))
    prog_list = list(prog_ids)

    lines = ["flowchart TD"]

    # Program nodes
    for p in progs:
        pid = p["program_id"]
        sid = _safe_mermaid_id(pid)
        label = p.get("business_name") or pid
        ptype = p.get("program_type", "")
        style = "online" if ptype == "ONLINE" else "batch" if ptype == "BATCH" else "default_prog"
        lines.append(f'    {sid}["{label}<br/>({pid})"]:::{style}')

    seen = set()

    # 1) Direct COBOL CALL edges within the module
    for e in cg:
        src, tgt = e["caller_program"], e.get("called_program")
        if src in prog_ids and tgt in prog_ids and f"call:{src}->{tgt}" not in seen:
            lines.append(f"    {_safe_mermaid_id(src)} --> {_safe_mermaid_id(tgt)}")
            seen.add(f"call:{src}->{tgt}")

    # 2) External COBOL CALLs (dashed)
    for e in cg:
        src, tgt = e["caller_program"], e.get("called_program")
        if tgt in (None, "UNKNOWN"):
            continue
        if src in prog_ids and tgt not in prog_ids and f"call:{src}->{tgt}" not in seen:
            tid = _safe_mermaid_id(tgt)
            lines.append(f'    {tid}(["{tgt}"]):::external')
            lines.append(f"    {_safe_mermaid_id(src)} -.-> {tid}")
            seen.add(f"call:{src}->{tgt}")
        elif tgt in prog_ids and src not in prog_ids and f"call:{src}->{tgt}" not in seen:
            sid = _safe_mermaid_id(src)
            lines.append(f'    {sid}(["{src}"]):::external')
            lines.append(f"    {sid} -.-> {_safe_mermaid_id(tgt)}")
            seen.add(f"call:{src}->{tgt}")

    # 3) CICS XCTL/LINK transfers from any module program
    try:
        cur.execute(f"""
            SELECT program_id, command, details_json
            FROM exec_cics
            WHERE program_id IN ({placeholders}) AND command IN ('XCTL','LINK')
        """, prog_list)
        for r in cur.fetchall():
            try:
                d = _json.loads(r["details_json"] or "{}")
                inner = d.get("details", d) or {}
                tgt = inner.get("program")
                if not tgt:
                    continue
                key = f"cics:{r['program_id']}->{tgt}"
                if key in seen:
                    continue
                tid = _safe_mermaid_id(tgt)
                if tgt not in prog_ids:
                    lines.append(f'    {tid}(["{tgt}"]):::external')
                lines.append(f"    {_safe_mermaid_id(r['program_id'])} -->|CICS {r['command']}| {tid}")
                seen.add(key)
            except Exception:
                pass
    except Exception:
        pass

    # 4) JCL parent jobs (above module programs)
    try:
        cur.execute(f"""
            SELECT DISTINCT program, job_name FROM jcl_steps
            WHERE program IN ({placeholders})
        """, prog_list)
        jcl_seen = set()
        for r in cur.fetchall():
            jname = r["job_name"]
            if jname not in jcl_seen:
                jid = "JCL_" + _safe_mermaid_id(jname)
                lines.append(f'    {jid}[/"{jname}.jcl"/]:::jcl')
                jcl_seen.add(jname)
            jid = "JCL_" + _safe_mermaid_id(jname)
            lines.append(f"    {jid} ==> {_safe_mermaid_id(r['program'])}")
    except Exception:
        pass

    # 5) Shared-copybook coupling between module programs (dashed, label = copybook)
    try:
        cur.execute(f"""
            SELECT cu1.program_id AS p1, cu2.program_id AS p2, cu1.copybook_name AS cb
            FROM copybook_usage cu1
            JOIN copybook_usage cu2 ON cu1.copybook_name = cu2.copybook_name
            WHERE cu1.program_id IN ({placeholders})
              AND cu2.program_id IN ({placeholders})
              AND cu1.program_id < cu2.program_id
        """, prog_list + prog_list)
        cb_pairs = {}  # (p1,p2) -> set(copybooks)
        for r in cur.fetchall():
            cb_pairs.setdefault((r["p1"], r["p2"]), set()).add(r["cb"])
        for (p1, p2), cbs in list(cb_pairs.items())[:20]:
            cb_label = sorted(cbs)[0]
            more = "" if len(cbs) == 1 else f" +{len(cbs)-1}"
            lines.append(
                f'    {_safe_mermaid_id(p1)} -..->|"{cb_label}{more}"| {_safe_mermaid_id(p2)}'
            )
    except Exception:
        pass

    lines.append("    classDef online fill:#388bfd,stroke:#58a6ff,color:#fff")
    lines.append("    classDef batch fill:#f0883e,stroke:#db6d28,color:#fff")
    lines.append("    classDef default_prog fill:#2ea043,stroke:#3fb950,color:#fff")
    lines.append("    classDef external fill:#30363d,stroke:#8b949e,color:#8b949e,stroke-dasharray:5 5")
    lines.append("    classDef jcl fill:#d29922,stroke:#9e6a03,color:#fff")
    return "\n".join(lines)


def _build_application_diagram(loader) -> str:
    """Application-level diagram: module subgraphs + inter-module COBOL CALLs +
    inter-module CICS XCTL/LINK + cross-module copybook coupling.
    Aggregated to module level so the diagram stays readable."""
    import json as _json
    from collections import defaultdict
    modules = loader.get_all_modules()
    cg = loader.get_call_graph()
    cur = loader.conn.cursor()

    # Map program → module business name
    prog_to_module = {}
    for m in modules:
        mname = m.get("business_name") or m.get("module_name", "Unknown")
        for p in m.get("programs", []):
            prog_to_module[p["program_id"]] = mname

    lines = ["flowchart TD"]

    # Module subgraphs
    for m in modules:
        mname = m.get("business_name") or m.get("module_name", "Unknown")
        mid = _safe_mermaid_id(mname)
        progs = m.get("programs", [])
        lines.append(f'    subgraph {mid}["{mname}"]')
        for p in progs:
            pid = p["program_id"]
            sid = _safe_mermaid_id(pid)
            lines.append(f'        {sid}["{pid}"]')
        lines.append("    end")

    seen_edges = set()

    # 1) Inter-module COBOL CALL edges (program → program)
    for e in cg:
        src, tgt = e["caller_program"], e.get("called_program")
        if tgt in (None, "UNKNOWN"):
            continue
        src_mod = prog_to_module.get(src)
        tgt_mod = prog_to_module.get(tgt)
        if src_mod and tgt_mod and src_mod != tgt_mod:
            key = f"call:{src}->{tgt}"
            if key not in seen_edges:
                lines.append(f"    {_safe_mermaid_id(src)} --> {_safe_mermaid_id(tgt)}")
                seen_edges.add(key)

    # 2) Inter-module CICS XCTL/LINK edges
    try:
        cur.execute("""
            SELECT program_id, command, details_json FROM exec_cics
            WHERE command IN ('XCTL','LINK')
        """)
        for r in cur.fetchall():
            try:
                d = _json.loads(r["details_json"] or "{}")
                inner = d.get("details", d) or {}
                tgt = inner.get("program")
                if not tgt:
                    continue
                src = r["program_id"]
                src_mod = prog_to_module.get(src)
                tgt_mod = prog_to_module.get(tgt)
                if src_mod and tgt_mod and src_mod != tgt_mod:
                    key = f"cics:{src}->{tgt}"
                    if key not in seen_edges:
                        lines.append(f"    {_safe_mermaid_id(src)} -->|CICS {r['command']}| {_safe_mermaid_id(tgt)}")
                        seen_edges.add(key)
            except Exception:
                pass
    except Exception:
        pass

    # 3) Cross-module copybook coupling — aggregate at MODULE level so it's readable.
    #    Pick the top N module pairs by number of shared copybooks.
    try:
        cur.execute("""
            SELECT cu1.program_id AS p1, cu2.program_id AS p2, COUNT(DISTINCT cu1.copybook_name) AS shared
            FROM copybook_usage cu1
            JOIN copybook_usage cu2 ON cu1.copybook_name = cu2.copybook_name
            WHERE cu1.program_id < cu2.program_id
            GROUP BY cu1.program_id, cu2.program_id
        """)
        module_couplings = defaultdict(int)
        for r in cur.fetchall():
            m1 = prog_to_module.get(r["p1"])
            m2 = prog_to_module.get(r["p2"])
            if m1 and m2 and m1 != m2:
                key = tuple(sorted((m1, m2)))
                module_couplings[key] += r["shared"]
        # Top 12 module pairs (dashed edge between subgraphs labelled with copybook count)
        top = sorted(module_couplings.items(), key=lambda x: -x[1])[:12]
        for (m1, m2), n in top:
            lines.append(
                f'    {_safe_mermaid_id(m1)} -..->|"{n} shared cb"| {_safe_mermaid_id(m2)}'
            )
    except Exception:
        pass

    # 4) Module styling
    lines.append("    classDef external fill:#30363d,stroke:#8b949e,color:#8b949e,stroke-dasharray:5 5")
    return "\n".join(lines)


def render_doc_text(doc_text: str, known_programs: list = None, program_file_map: dict = None,
                    known_copybooks: list = None, copybook_file_map: dict = None):
    """
    Render generated documentation as polished HTML.
    Converts markdown → styled HTML.
    Highlights program IDs and copybook names as clickable chips
    with a reference panel below for reliable Streamlit navigation.
    """
    import re
    import streamlit as st

    if not doc_text:
        return

    # ── Convert markdown → HTML ──────────────────────────────────────────────
    text = doc_text

    def replace_code_block(m):
        lang = m.group(1) or ""
        code = m.group(2).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<pre><code class="lang-{lang}">{code}</code></pre>'

    text = re.sub(r'```(\w*)\n([\s\S]*?)```', replace_code_block, text)

    text = re.sub(r'^#{4} (.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^#{3} (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^#{2} (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^#{1} (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)

    text = re.sub(r'^---+$', '<hr>', text, flags=re.MULTILINE)

    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'\*\*(.+?)\*\*',     r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*',         r'<em>\1</em>', text)

    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', text, flags=re.MULTILINE)

    def make_list(m):
        items = re.findall(r'^[-*•] (.+)$', m.group(0), re.MULTILINE)
        return '<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>'

    text = re.sub(r'((?:^[-*•] .+\n?)+)', make_list, text, flags=re.MULTILINE)

    def make_ol(m):
        items = re.findall(r'^\d+\. (.+)$', m.group(0), re.MULTILINE)
        return '<ol>' + ''.join(f'<li>{i}</li>' for i in items) + '</ol>'

    text = re.sub(r'((?:^\d+\. .+\n?)+)', make_ol, text, flags=re.MULTILINE)

    # Paragraph wrapping
    lines = text.split('\n')
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('<'):
            out.append(stripped)
        else:
            out.append(f'<p>{stripped}</p>')
    text = '\n'.join(out)

    # ── Highlight program IDs ────────────────────────────────────────────────
    found_programs = []
    # Build a set of known program IDs for quick lookup
    prog_set = set(known_programs) if known_programs else set()
    copy_set = set(known_copybooks) if known_copybooks else set()

    if known_programs:
        for pid in sorted(known_programs, key=len, reverse=True):
            if pid in doc_text:
                found_programs.append(pid)
                # Use a placeholder to avoid nested replacements
                placeholder = f'__PROG_{pid}__'
                text = re.sub(
                    rf'(?<![A-Z0-9\-_/="]){re.escape(pid)}(?![A-Z0-9\-_/="])',
                    placeholder,
                    text,
                )
                # Now replace placeholder with the link
                text = text.replace(
                    placeholder,
                    f'<a href="?nav=Explorer&amp;prog={pid}" target="_self" class="prog-chip">{pid}</a>',
                )

    # ── Highlight copybook names ─────────────────────────────────────────────
    found_copybooks = []

    if known_copybooks:
        for cb in sorted(known_copybooks, key=len, reverse=True):
            if cb in doc_text:
                found_copybooks.append(cb)
                placeholder = f'__COPY_{cb}__'
                text = re.sub(
                    rf'(?<![A-Z0-9\-_/="]){re.escape(cb)}(?![A-Z0-9\-_/="])',
                    placeholder,
                    text,
                )
                text = text.replace(
                    placeholder,
                    f'<a href="?nav=FileViewer&amp;copy={cb}" target="_self" class="copy-chip">{cb}</a>',
                )

    # ── Render with st.components.v1.html (iframe — avoids Streamlit sanitizer) ──
    height = min(max(len(doc_text) // 2, 800), 12000)

    full_html = f"""
<div class="doc-body">
    <style>
    body {{
        background-color: #0e1117;
        color: #d4d4d4;
        font-family: 'Inter', sans-serif;
        margin: 0; padding: 10px;
    }}
    .doc-body {{
        color: #d4d4d4;
        font-size: 15px;
        line-height: 1.8;
    }}
    .doc-body h1 {{ color: #ffffff; border-bottom: 2px solid #2d2d2d; }}
    .doc-body h2 {{ color: #58a6ff; }}
    .doc-body h3 {{ color: #79c0ff; }}
    .doc-body h4 {{ color: #a5d6ff; }}
    .doc-body p  {{ color: #d4d4d4; }}
    .doc-body li {{ color: #d4d4d4; }}
    .doc-body strong {{ color: #ffffff; }}
    .doc-body code {{
        background: #161b22;
        color: #79c0ff;
        padding: 1px 4px;
        border-radius: 3px;
    }}
    .doc-body pre {{
        background: #161b22;
        padding: 12px;
        border-radius: 6px;
        overflow-x: auto;
    }}
    .doc-body blockquote {{
        border-left: 3px solid #58a6ff;
        padding-left: 12px;
        color: #8b949e;
    }}

    a.prog-chip {{
        background: #0d2b1a;
        color: #3fb950;
        border: 1px solid #1a4731;
        padding: 1px 6px;
        border-radius: 3px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 13px;
        text-decoration: underline dotted;
        text-underline-offset: 3px;
        cursor: pointer;
    }}
    a.prog-chip:hover {{
        background: #0f3d23;
        color: #56d364;
        border-color: #238636;
    }}

    a.copy-chip {{
        background: #1a1a2e;
        color: #a78bfa;
        border: 1px solid #312e81;
        padding: 1px 6px;
        border-radius: 3px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 13px;
        text-decoration: underline dotted;
        text-underline-offset: 3px;
        cursor: pointer;
    }}
    a.copy-chip:hover {{
        background: #252550;
        color: #c4b5fd;
        border-color: #4c1d95;
    }}
    </style>

    {text}

    <script>
    document.addEventListener('click', function(e) {{
        var link = e.target.closest('a.prog-chip, a.copy-chip');
        if (!link) return;
        e.preventDefault();
        var href = link.getAttribute('href');
        var base = window.parent.location.origin + window.parent.location.pathname;
        window.parent.location.href = base + href.replace(/&amp;/g, '&');
    }});
    </script>
</div>
"""

    st.components.v1.html(full_html, height=height, scrolling=True)

    # ── Clickable reference panel ────────────────────────────────────────────
    has_refs = found_programs or found_copybooks
    if has_refs:
        st.markdown("---")

    # Programs
    if found_programs:
        st.markdown(
            f"**Programs referenced ({len(found_programs)}) — click to open:**"
        )
        cols = st.columns(min(len(found_programs), 6))
        for i, pid in enumerate(found_programs[:30]):
            with cols[i % len(cols)]:
                file_path = program_file_map.get(pid) if program_file_map else None
                if file_path and os.path.isfile(file_path):
                    if st.button(f"📄 {pid}", key=f"ref_file_{pid}", use_container_width=True):
                        st.session_state.current_page = "File Viewer"
                        st.session_state.open_file_path = file_path
                        st.rerun()
                else:
                    if st.button(f"📄 {pid}", key=f"ref_prog_{pid}", use_container_width=True):
                        st.session_state.current_page = "Explorer"
                        st.session_state.explorer_program_select = pid
                        st.rerun()

    # Copybooks
    if found_copybooks:
        st.markdown(
            f"**Copybooks referenced ({len(found_copybooks)}) — click to open:**"
        )
        cols = st.columns(min(len(found_copybooks), 6))
        for i, cb in enumerate(found_copybooks[:30]):
            with cols[i % len(cols)]:
                file_path = copybook_file_map.get(cb) if copybook_file_map else None
                if file_path and os.path.isfile(file_path):
                    if st.button(f"📋 {cb}", key=f"ref_copy_{cb}", use_container_width=True):
                        st.session_state.current_page = "File Viewer"
                        st.session_state.open_file_path = file_path
                        st.rerun()
                else:
                    if st.button(f"📋 {cb}", key=f"ref_copy_nf_{cb}", use_container_width=True):
                        st.info(f"Source file for copybook {cb} not found in dataset.")
    
def page_doc_generator():
    st.header("English Documentation Generator")
    st.markdown("Generate a comprehensive English narrative document for any program or module — treating the system as a connected graph.")

    try:
        loader = db_connect()
        programs = loader.get_all_programs()
        modules  = loader.get_all_modules()
    except Exception as e:
        st.error(f"Database not ready. ({e})")
        return

    db_path = os.getenv("DB_PATH", "data/cobol_knowledge.db")

    # ── Mode selector ──────────────────────────────────────────────────────────
    col_mode, col_depth = st.columns([1, 1])
    with col_mode:
        mode = st.radio(
            "Documentation Mode",
            ["Program", "Module", "Application"],
            horizontal=True,
            help="Application generates a full system Architecture Document covering all programs and modules.",
        )
    with col_depth:
        if mode == "Program":
            depth = st.slider(
                "Graph Depth (hops)", min_value=1, max_value=2, value=1,
                help="1 = direct connections only · 2 = connections of connections",
            )
        else:
            depth = 1

    # ── Subject selector ───────────────────────────────────────────────────────
    if mode == "Program":
        program_ids = sorted([p["program_id"] for p in programs])
        subject     = st.selectbox("Select Program", program_ids, key="docgen_program_select")
        cache_key   = f"doc_{subject}_depth{depth}"
        st.caption(
            f"Will include {subject} + all programs it calls/is called by "
            f"(up to {depth} hop{'s' if depth > 1 else ''} away)"
        )

    elif mode == "Module":
        module_names = [m.get("business_name") or m.get("module_name", "") for m in modules]
        subject      = st.selectbox("Select Module", module_names, key="docgen_module_select")
        cache_key    = f"doc_module_{subject}"
        sel_module   = next(
            (m for m in modules if (m.get("business_name") or m.get("module_name")) == subject),
            None,
        )
        if sel_module:
            progs_in_module = sel_module.get("programs", [])
            st.caption(
                f"Module contains {len(progs_in_module)} programs: "
                + ", ".join(p["program_id"] for p in progs_in_module[:8])
                + ("..." if len(progs_in_module) > 8 else "")
            )

    else:  # Application
        subject   = "Full Application"
        cache_key = "doc_application_full"
        st.caption(
            f"Will generate a system-wide Architecture Document covering all "
            f"{len(programs)} programs across {len(modules)} modules."
        )

    # ── Check DB for existing saved doc ───────────────────────────────────────
    saved_doc = loader.get_generated_doc(mode, subject)

    # ── Buttons ────────────────────────────────────────────────────────────────
    col_btn, col_regen, col_clear = st.columns([2, 1, 1])
    with col_btn:
        generate = st.button(
            "Generate Documentation" if not saved_doc else "✓ Documentation Ready",
            type="primary",
            use_container_width=True,
            disabled=bool(saved_doc),   # greyed out if already saved
        )
    with col_regen:
        regenerate = st.button(
            "Regenerate",
            use_container_width=True,
            help="Re-run the agent pipeline and overwrite the saved document.",
        )
    with col_clear:
        if st.button("Clear Cache", use_container_width=True):
            if cache_key in st.session_state:
                del st.session_state[cache_key]
            st.rerun()

    # ── Determine whether to run the pipeline ─────────────────────────────────
    run_pipeline = (generate and not saved_doc) or regenerate

    # ── Load or generate ───────────────────────────────────────────────────────
    if run_pipeline or saved_doc or cache_key in st.session_state:

        if run_pipeline:
            # Clear stale session cache so we show the fresh result
            if cache_key in st.session_state:
                del st.session_state[cache_key]

            spinner_label = (
                f"Running agent pipeline for {subject} "
                f"(Writer → Critique → Formatter → Save)…"
            )
            with st.spinner(spinner_label):
                # Build context
                if mode == "Program":
                    prog_data  = _fetch_program_subgraph(loader, subject, depth)
                    context    = _build_llm_context(prog_data, mode, subject, loader=loader)
                    prog_count = len(prog_data)

                elif mode == "Module":
                    prog_data = []
                    if sel_module:
                        for p in sel_module.get("programs", []):
                            details = loader.get_program_details(p["program_id"])
                            if details:
                                prog_data.append(details)
                    context    = _build_llm_context(prog_data, mode, subject, loader=loader)
                    prog_count = len(prog_data)

                else:  # Application
                    app_data   = _fetch_application_subgraph(loader)
                    context    = _build_application_llm_context(app_data)
                    prog_count = app_data["stats"]["total_programs"]

                # Run the full agent pipeline — saves to DB internally
                try:
                    doc_text = run_doc_pipeline(mode, subject, context, db_path)
                except Exception as exc:
                    msg = str(exc)
                    if "127.0.0.1:9" in msg or "tcp handshaker shutdown" in msg:
                        st.error(
                            "LLM connection failed because proxy environment variables point to "
                            "127.0.0.1:9. Clear HTTP_PROXY, HTTPS_PROXY, and ALL_PROXY, then retry."
                        )
                    else:
                        st.error(f"LLM document generation failed: {exc}")
                    st.stop()

            st.session_state[cache_key]                  = doc_text
            st.session_state[f"{cache_key}_prog_count"]  = prog_count
            st.session_state[f"{cache_key}_from_agents"] = True

        elif saved_doc and cache_key not in st.session_state:
            # Serve from DB — no LLM call needed
            doc_text   = saved_doc
            prog_count = 0
            st.session_state[cache_key]                  = doc_text
            st.session_state[f"{cache_key}_prog_count"]  = prog_count
            st.session_state[f"{cache_key}_from_agents"] = False

        doc_text   = st.session_state.get(cache_key, "")
        prog_count = st.session_state.get(f"{cache_key}_prog_count", 0)
        from_agents = st.session_state.get(f"{cache_key}_from_agents", False)

        # ── Status banner ──────────────────────────────────────────────────────
        if from_agents:
            if mode == "Application":
                st.success(
                    f"Generated via agent pipeline from {prog_count} programs "
                    f"across {len(modules)} modules — saved to DB."
                )
            else:
                st.success(
                    f"Generated via agent pipeline from {prog_count} programs — saved to DB."
                )
        else:
            st.info("Loaded from saved documentation database. Click Regenerate to refresh.")

        # ── Simple Diagrams ────────────────────────────────────────────────────
        with st.expander("Flowchart Diagram", expanded=True):
            try:
                diag_loader = db_connect()
                if mode == "Program":
                    diagram_code = _build_program_call_diagram(diag_loader, subject, depth)
                    st.caption("Call graph: callers (orange) → this program (blue) → callees (green)")
                elif mode == "Module":
                    sel_mod = next(
                        (m for m in modules
                         if (m.get("business_name") or m.get("module_name")) == subject),
                        None,
                    )
                    if sel_mod:
                        diagram_code = _build_module_diagram(diag_loader, sel_mod)
                        st.caption("Module programs and call relationships. Dashed = external calls.")
                    else:
                        diagram_code = None
                else:  # Application
                    diagram_code = _build_application_diagram(diag_loader)
                    st.caption("Application-level: modules as groups, inter-module call edges shown.")
                diag_loader.close()

                if diagram_code:
                    render_mermaid(diagram_code, height=500)
            except Exception as e:
                st.warning(f"Could not render diagram: {e}")

        st.divider()
        # Build program_id / copybook → source file path mappings
        repo_path_local = st.session_state.get("_repo_path", "./carddemo/app")
        _prog_file_map = {}
        _copy_file_map = {}
        if repo_path_local and os.path.exists(repo_path_local):
            for root, _, fnames in os.walk(repo_path_local):
                for fn in fnames:
                    fnu = fn.upper()
                    name_no_ext = fnu.rsplit(".", 1)[0]
                    fp = os.path.join(root, fn)
                    if fnu.endswith((".CBL", ".COB")):
                        _prog_file_map[name_no_ext] = fp
                    elif fnu.endswith(".CPY"):
                        _copy_file_map[name_no_ext] = fp
                    elif fnu.endswith(".BMS"):
                        _prog_file_map[name_no_ext] = fp

        # Gather known copybook names from DB
        try:
            _copybooks = loader.get_copybooks()
            _known_cbs = [cb["copybook_name"] for cb in _copybooks]
        except Exception:
            _known_cbs = list(_copy_file_map.keys())

        render_doc_text(
            doc_text,
            [p["program_id"] for p in programs],
            program_file_map=_prog_file_map,
            known_copybooks=_known_cbs,
            copybook_file_map=_copy_file_map,
        )
        st.divider()

        # ── Download buttons ───────────────────────────────────────────────────
        col_md, col_pdf = st.columns(2)
        with col_md:
            st.download_button(
                label="Download as Markdown",
                data=doc_text.encode("utf-8"),
                file_name=f"{subject.replace(' ', '_')}_documentation.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_pdf:
            with st.spinner("Generating PDF…"):
                try:
                    pdf_bytes = _markdown_to_pdf(doc_text, f"{subject} — Documentation")
                    st.download_button(
                        label="Download as PDF",
                        data=pdf_bytes,
                        file_name=f"{subject.replace(' ', '_')}_documentation.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                except Exception as e:
                    st.warning(f"PDF generation failed: {e}. Use Markdown download instead.")

    loader.close()

# 
# Main Layout
# 

# ── Init ──────────────────────────────────────────────────────────────────────
if "current_page" not in st.session_state:
    st.session_state.current_page = "Overview"

# ── Handle query-param navigation from clickable chips ────────────────────────
_qp = st.query_params
if "nav" in _qp:
    nav_target = _qp["nav"]
    if nav_target == "Explorer" and "prog" in _qp:
        st.session_state.current_page = "Explorer"
        st.session_state.explorer_program_select = _qp["prog"]
        st.query_params.clear()
        st.rerun()
    elif nav_target == "FileViewer" and "copy" in _qp:
        cb_name = _qp["copy"]
        # Resolve copybook name to file path
        repo_path_qp = st.session_state.get("_repo_path", "./carddemo/app")
        _found_fp = None
        if repo_path_qp and os.path.exists(repo_path_qp):
            for root, _, fnames in os.walk(repo_path_qp):
                for fn in fnames:
                    if fn.upper().rsplit(".", 1)[0] == cb_name and fn.upper().endswith(".CPY"):
                        _found_fp = os.path.join(root, fn)
                        break
                if _found_fp:
                    break
        if _found_fp:
            st.session_state.current_page = "File Viewer"
            st.session_state.open_file_path = _found_fp
        else:
            # Fallback: try opening in explorer as a program
            st.session_state.current_page = "Explorer"
            st.session_state.explorer_program_select = cb_name
        st.query_params.clear()
        st.rerun()

repo_path, output_dir = render_sidebar()

# ── Route to current page ──────────────────────────────────────────────────────
_page = st.session_state.get("current_page", "Overview")

if   _page == "Overview":          page_overview()
elif _page == "Call Graph":        page_call_graph()
elif _page == "Dependency Matrix": page_dependency_matrix()
elif _page == "Data Flow":         page_data_flow()
elif _page == "Modules":           page_modules()
elif _page == "Explorer":          page_explorer()
elif _page == "Doc Generator":     page_doc_generator()
elif _page == "JCL Jobs":          page_jcl()
elif _page == "CICS Commands":     page_cics()
elif _page == "SQL Operations":    page_sql()
elif _page == "Migration":         page_migration()
elif _page == "Rules":             page_rules()
elif _page == "Search":            page_search(repo_path)
elif _page == "File Viewer":       page_file_viewer()
