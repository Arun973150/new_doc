"""
Agentic Documentation Pipeline
LangGraph state machine: Writer → Critique → (loop max 2x) → Formatter → Save

Works for all three modes: Program, Module, Application.
"""

import os
import json
import re
import functools
from typing import TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

from rich.console import Console
console = Console(force_terminal=True, highlight=False)


# ── State ──────────────────────────────────────────────────────────────────────

class DocAgentState(TypedDict):
    mode:             str   # "Program", "Module", "Application"
    subject:          str   # program ID, module name, or "Full Application"
    context:          str   # pre-built context string from app.py helpers
    draft:            str   # document produced by Writer
    critique_feedback:str   # issues found by Critique
    critique_passed:  bool  # True when Critique is satisfied
    formatted_doc:    str   # final cleaned document
    iteration:        int   # how many write→critique loops have run
    max_iterations:   int   # cap — default 2
    saved:            bool


# ── LLM factory ───────────────────────────────────────────────────────────────

def _get_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.environ.get("GEMINI_API_KEY"),
        temperature=0.3,
        max_tokens=65536,
    )


# ── Prompts ────────────────────────────────────────────────────────────────────

WRITER_SYSTEM = (
    "You are a chief software architect writing technical documentation "
    "for a legacy COBOL mainframe modernisation team. "
    "Write clearly, specifically, and completely. Never truncate sections."
)

CRITIQUE_SYSTEM = """You are a senior technical editor reviewing COBOL documentation for a modernisation team.
Your job is to find gaps, vague statements, and missing sections — not to rewrite, just to flag issues.
Respond ONLY with JSON: {"passed": true/false, "issues": ["issue 1", "issue 2"]}
If the document is complete respond with {"passed": true, "issues": []}"""

FORMATTER_SYSTEM = (
    "You are a technical documentation formatter. "
    "Fix heading levels, remove duplicate sections, ensure consistent formatting. "
    "Do NOT remove or summarise any content — only clean structure. "
    "Return the complete cleaned document."
)


def _writer_prompt(mode: str, subject: str, context: str, feedback: str = "") -> str:
    feedback_block = (
        f"\n\nPREVIOUS CRITIQUE FEEDBACK — address every point below:\n{feedback}"
        "\n\nRewrite the full document addressing all issues above."
    ) if feedback else ""

    if mode == "Program":
        instructions = f"""Write a comprehensive technical documentation document for "{subject}" and all its connected programs.

The document must contain these numbered sections:
1. Executive Summary — what this program does, who triggers it, business importance
2. Program Descriptions — each program in execution order: what it does, data read/written, business decisions, output produced
3. Program Connectivity and Data Flow — which program calls which, shared data structures, data flow between programs
4. Critical Business Rules and Validation Logic — list specific rules with conditions and actions
5. Migration Notes — complexity rating, modern equivalent, recommended microservice boundary

Write in flowing prose with clear numbered headings. Reference actual program IDs, paragraph names, and file names throughout."""

    elif mode == "Module":
        instructions = f"""Write a comprehensive module specification document for the "{subject}" module.

The document must contain these numbered sections:
1. Module Overview — business capability this module provides, who uses it, its role in the overall system
2. Programs in This Module — each program with a clear one-paragraph description of its purpose
3. Internal Flow — how programs within this module interact, the sequence of operations end-to-end
4. Data Architecture — files, datasets, and shared copybooks this module uses
5. Key Business Rules and Validations — enforced by programs in this module
6. External Dependencies — what other modules/programs this module depends on and what depends on it
7. Migration Strategy — recommended service boundary, suggested modern architecture, migration order for programs

Write in flowing prose with numbered headings. Reference specific program IDs and file names."""

    else:  # Application
        instructions = """Write a comprehensive Application Architecture Document.

CRITICAL FORMATTING RULES:
- Do NOT use markdown tables anywhere. Use numbered lists and prose instead.
- Write every module subsection in full — do not skip any module.
- Do not truncate any section.

The document must contain these numbered sections:
1. Executive Summary — what the application does, who uses it, business criticality, case for modernisation (2-3 paragraphs)
2. System Architecture Overview — online CICS tier vs batch tier, entry points, schedulers, user touchpoints
3. Module Breakdown — one numbered subsection per module containing: business domain, list of programs with one-sentence roles, how programs interact internally
4. Inter-Module Data Flow — which modules depend on which, shared files/copybooks coupling modules, 3-4 critical data paths as step-by-step numbered flows
5. Business Rule Inventory — rule categories with counts, top 5 highest-density programs and what kinds of rules they contain
6. Migration Roadmap — for EACH module write: target microservice name, migration order (1=first) with justification, key technical risks, suggested tech stack. End with an overall ordered migration sequence as a numbered list.
7. Risk Register — top 7 highest-risk components as a numbered list, each with: why it is high risk, concrete mitigation strategy"""

    return f"""{instructions}{feedback_block}

SYSTEM DATA:
{context}

Write the complete document now:"""


def _critique_prompt(mode: str, subject: str, draft: str) -> str:
    required = {
        "Program":     ["Executive Summary", "Program Descriptions", "Data Flow", "Business Rules", "Migration Notes"],
        "Module":      ["Module Overview", "Programs in This Module", "Internal Flow", "Data Architecture", "Business Rules", "External Dependencies", "Migration Strategy"],
        "Application": ["Executive Summary", "System Architecture", "Module Breakdown", "Inter-Module Data Flow", "Business Rule Inventory", "Migration Roadmap", "Risk Register"],
    }
    sections = ", ".join(required.get(mode, []))

    return f"""Review this {mode}-level COBOL documentation for "{subject}".

Check for ALL of the following:
1. Are ALL required sections present and complete? Required sections: {sections}
2. Are there any vague, generic, or placeholder statements ("TBD", "not available", "various programs")?
3. Are specific program IDs, module names, file names referenced throughout — not just in the data section?
4. For Application mode: does the Migration Roadmap cover EVERY module individually? Does the Risk Register have exactly 7 entries?
5. Is any section truncated, cut off mid-sentence, or significantly shorter than expected?

DOCUMENT TO REVIEW:
{draft[:9000]}{"...[truncated for review]" if len(draft) > 9000 else ""}

Respond with JSON only: {{"passed": true/false, "issues": ["specific issue 1", "specific issue 2"]}}"""


# ── Node functions ─────────────────────────────────────────────────────────────

def _write_node(state: DocAgentState) -> dict:
    iteration = state.get("iteration", 0)
    feedback  = state.get("critique_feedback", "")

    if iteration == 0:
        console.print(f"[cyan]  Writer: generating {state['mode']}-level doc for '{state['subject']}'...[/cyan]")
    else:
        console.print(f"[cyan]  Writer: revision {iteration} — addressing critique feedback...[/cyan]")

    llm      = _get_llm()
    prompt   = _writer_prompt(state["mode"], state["subject"], state["context"], feedback)
    response = llm.invoke([SystemMessage(content=WRITER_SYSTEM), HumanMessage(content=prompt)])

    return {"draft": response.content, "iteration": iteration + 1}


def _critique_node(state: DocAgentState) -> dict:
    console.print(f"[cyan]  Critique: reviewing draft (iteration {state['iteration']})...[/cyan]")

    llm      = _get_llm()
    prompt   = _critique_prompt(state["mode"], state["subject"], state["draft"])
    response = llm.invoke([SystemMessage(content=CRITIQUE_SYSTEM), HumanMessage(content=prompt)])

    content = response.content.strip()
    try:
        if "```" in content:
            content = content.split("```")[1].replace("json", "").strip()
        result = json.loads(content)
    except Exception:
        m = re.search(r'\{[\s\S]*\}', content)
        result = json.loads(m.group()) if m else {"passed": True, "issues": []}

    passed = result.get("passed", True)
    issues = result.get("issues", [])

    if passed:
        console.print("[green]  Critique: document passed quality check.[/green]")
    else:
        console.print(f"[yellow]  Critique: {len(issues)} issue(s) found — requesting revision.[/yellow]")
        for iss in issues:
            console.print(f"[yellow]    · {iss}[/yellow]")

    return {
        "critique_passed":   passed,
        "critique_feedback": "\n".join(f"- {i}" for i in issues),
    }


def _format_node(state: DocAgentState) -> dict:
    console.print("[cyan]  Formatter: cleaning document structure...[/cyan]")
    llm      = _get_llm()
    response = llm.invoke([
        SystemMessage(content=FORMATTER_SYSTEM),
        HumanMessage(content=f"Clean and format this document. Return the complete document:\n\n{state['draft']}"),
    ])
    return {"formatted_doc": response.content}


def _save_node(state: DocAgentState, db_path: str) -> dict:
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT OR REPLACE INTO generated_docs (mode, subject, document_text, generated_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (state["mode"], state["subject"], state["formatted_doc"]))
        conn.commit()
        conn.close()
        console.print(f"[green]  Save: stored in DB ({state['mode']} / {state['subject']})[/green]")
        return {"saved": True}
    except Exception as e:
        console.print(f"[yellow]  Save: warning — could not save to DB: {e}[/yellow]")
        return {"saved": False}


def _should_revise(state: DocAgentState) -> str:
    if not state.get("critique_passed", False) and state.get("iteration", 0) < state.get("max_iterations", 2):
        return "revise"
    return "format"


# ── Graph builder ──────────────────────────────────────────────────────────────

def _build_pipeline(db_path: str):
    workflow = StateGraph(DocAgentState)

    workflow.add_node("write",    _write_node)
    workflow.add_node("critique", _critique_node)
    workflow.add_node("format",   _format_node)
    workflow.add_node("save",     functools.partial(_save_node, db_path=db_path))

    workflow.add_edge(START,      "write")
    workflow.add_edge("write",    "critique")
    workflow.add_conditional_edges("critique", _should_revise, {
        "revise": "write",
        "format": "format",
    })
    workflow.add_edge("format",   "save")
    workflow.add_edge("save",     END)

    return workflow.compile()


# ── Public API ─────────────────────────────────────────────────────────────────

def run_doc_pipeline(mode: str, subject: str, context: str, db_path: str) -> str:
    """
    Run Writer → Critique → (loop ≤2x) → Formatter → Save.
    Returns the final formatted document text.
    """
    console.print(f"[cyan]Doc Pipeline: {mode} / {subject}[/cyan]")

    pipeline = _build_pipeline(db_path)

    initial: DocAgentState = {
        "mode":             mode,
        "subject":          subject,
        "context":          context,
        "draft":            "",
        "critique_feedback":"",
        "critique_passed":  False,
        "formatted_doc":    "",
        "iteration":        0,
        "max_iterations":   2,
        "saved":            False,
    }

    final = pipeline.invoke(initial)
    doc   = final.get("formatted_doc") or final.get("draft", "")
    console.print(
        f"[green]Doc Pipeline: done — {final.get('iteration')} iteration(s), "
        f"saved={final.get('saved')}[/green]"
    )
    return doc