"""Builders for the four context-type sources (proposal Section 7.1/7.2): past_tickets,
design_documents, coding_conventions, codebase_summaries.

Each function returns document-level Chunk objects, one per logical source unit (one per issue,
one per xdoc file, one per convention file, one per .java file). Splitting these into the fixed
500/50 embed-ready pieces is done by the index-build step via src/retrieval/chunking.py, not here,
so the tested splitter stays the single place that logic lives.

Metadata boundary (CLAUDE.md, do not weaken): only issue.summary/description ever feed a
context-type source in this file. issue_component, issue_fix_version, and non-containment
issue_link rows are sampling/analysis-only and must never be read here.

codebase_summary_chunks is the one builder that costs money: it calls an LLM once per .java file
and caches the result to disk, so re-running only pays for files that aren't cached yet. It refuses
to spend uncached calls unless the caller passes confirm=True, precisely so a full 1088-file sweep
can't happen by accident.
"""

from __future__ import annotations

import html.entities
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from src.conditions import ContextType
from src.data.seoss_loader import SeossLoader
from src.llm.base import LLMClient
from src.retrieval.text_clean import strip_jira_markup

# Forrest xdocs files that are pure navigation/config, not documentation prose (confirmed: they
# parse to zero extracted text).
_DESIGN_DOC_SKIP = {"site.xml", "tabs.xml"}

_ENTITY_RE = re.compile(r"&([a-zA-Z][a-zA-Z0-9]*);")
_XML_BUILTIN_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


@dataclass
class Chunk:
    id: str
    text: str
    context_type: ContextType
    metadata: dict = field(default_factory=dict)


def _fix_undeclared_entities(xml_text: str) -> str:
    """Some xdocs files use bare HTML named entities (&nbsp;, &lsquo;, ...) with no DTD to resolve
    them, which makes ElementTree raise UndefinedEntity. Substitute known HTML5 named entities
    before parsing; leaves the 5 built-in XML entities untouched."""

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name in _XML_BUILTIN_ENTITIES:
            return match.group(0)
        char = html.entities.html5.get(name + ";") or html.entities.html5.get(name)
        return char if char is not None else match.group(0)

    return _ENTITY_RE.sub(repl, xml_text)


def past_tickets_chunks(loader: SeossLoader) -> list[Chunk]:
    """One chunk per issue in the full past-tickets candidate pool (New Feature/Improvement,
    resolution='Fixed', description floor - the same 776-issue pool sampling draws the frozen 20
    from). This is the full corpus, not the frozen 20, and it is not excluded per-requirement here:
    the same fixed index is shared across all requirements, and excluding the requirement's own
    issue happens as a query-time metadata filter (index.py/hybrid.py), not at build time. Each
    chunk's metadata carries issue_id so that filter has something to match on."""
    issues = loader.issues(types=("New Feature", "Improvement"))
    chunks: list[Chunk] = []
    for issue in issues:
        text = strip_jira_markup("\n".join(p for p in (issue.summary, issue.description) if p))
        if not text:
            continue
        chunks.append(Chunk(
            id=f"past_ticket::{issue.issue_id}",
            text=text,
            context_type=ContextType.PAST_TICKETS,
            metadata={"issue_id": issue.issue_id},
        ))
    print(f"Built {len(chunks)} past-ticket chunks from {len(issues)} issues")
    print(chunks[:5])
    return chunks


def design_document_chunks(docs_dir: str | Path) -> list[Chunk]:
    """One chunk per Forrest xdocs file (design_docs context type), text extracted from the XML
    element tree. Jira-markup cleanup does not apply here; this isn't Jira content."""
    docs_dir = Path(docs_dir)
    chunks: list[Chunk] = []
    for path in sorted(docs_dir.glob("*.xml")):
        if path.name in _DESIGN_DOC_SKIP:
            continue
        raw = path.read_text(errors="replace")
        try:
            root = ET.fromstring(_fix_undeclared_entities(raw))
        except ET.ParseError:
            continue
        text = " ".join(t.strip() for t in root.itertext() if t.strip())
        if not text:
            continue
        chunks.append(Chunk(
            id=f"design_doc::{path.stem}",
            text=text,
            context_type=ContextType.DESIGN_DOCS,
            metadata={"source": path.name},
        ))
    print(f"Built {len(chunks)} design-document chunks")
    print(chunks[:5])
    return chunks


def coding_convention_chunks(repo_path: str | Path) -> list[Chunk]:
    """One chunk each for checkstyle.xml and README.txt (coding_conventions context type), kept as
    raw text rather than XML-parsed: checkstyle's value here is in its rule comments, not a
    validated structure."""
    repo_path = Path(repo_path)
    sources = (
        ("checkstyle", repo_path / "test" / "checkstyle.xml"),
        ("readme", repo_path / "README.txt"),
    )
    chunks: list[Chunk] = []
    for name, path in sources:
        if not path.exists():
            continue
        text = path.read_text(errors="replace").strip()
        if not text:
            continue
        chunks.append(Chunk(
            id=f"coding_convention::{name}",
            text=text,
            context_type=ContextType.CODING_CONVENTIONS,
            metadata={"source": str(path.relative_to(repo_path))},
        ))
    print(f"Built {len(chunks)} coding-convention chunks")
    print(chunks[:5])
    return chunks


# -- codebase_summaries -------------------------------------------------------------------------
# One LLM-written summary per main-source .java file, cached to disk so re-running only pays for
# files not yet summarized. Purely descriptive by design (researcher decision, CLAUDE.md): every
# term in a summary must be traceable to something literally in the file. The model is explicitly
# told not to guess at related Pig Latin operators/keywords - that speculative-association job
# belongs to lexical retrieval over real symbols already in the code, not to a synthetic summary
# that would pollute retrieval unauditably if the model guessed wrong.

_SUMMARY_SYSTEM_PROMPT = (
    "You summarize a single Java source file from the Apache Pig codebase for a retrieval index. "
    "Write a short, purely descriptive summary: what the file does, its role in the codebase, and "
    "the key classes/methods it defines. Quote only real identifiers that literally appear in the "
    "file (class names, method names, constants) - never invent or infer identifiers. Do not list "
    "or infer Pig Latin operators, keywords, or behaviours unless they are explicitly named in the "
    "file's code or comments, and do not speculate about how this file relates to other files. "
    "Every term in your summary must be traceable to something actually in this file. Keep it to "
    "3-6 sentences."
)

_MAX_FILE_CHARS = 40_000  # ~10k tokens; covers all but the largest handful of files in this repo


def _cache_key(src_root: Path, path: Path) -> str:
    return path.relative_to(src_root).as_posix().replace("/", "__")


def _cache_path(cache_dir: Path, src_root: Path, path: Path) -> Path:
    return cache_dir / f"{_cache_key(src_root, path)}.json"


def _read_cache(cache_dir: Path, src_root: Path, path: Path) -> dict | None:
    cp = _cache_path(cache_dir, src_root, path)
    if not cp.exists():
        return None
    try:
        return json.loads(cp.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(cache_dir: Path, src_root: Path, path: Path, summary: str, model: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cp = _cache_path(cache_dir, src_root, path)
    rel = path.relative_to(src_root).as_posix()
    cp.write_text(json.dumps({
        "file_path": rel,
        "summary": summary,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


def _summarize_file(llm: LLMClient, src_root: Path, path: Path) -> str:
    rel = path.relative_to(src_root).as_posix()
    code = path.read_text(errors="replace")
    truncated = len(code) > _MAX_FILE_CHARS
    if truncated:
        code = code[:_MAX_FILE_CHARS]
    note = "\n\n[file truncated for length]" if truncated else ""
    prompt = f"File: {rel}\n\n{code}{note}"
    return llm.complete(prompt, system=_SUMMARY_SYSTEM_PROMPT).text.strip()


def pending_summary_files(
    repo_path: str | Path, cache_dir: str | Path, file_paths: list[Path] | None = None
) -> list[Path]:
    """Files (relative to the main source root) that don't have a cached summary yet. Pure
    lookup, no LLM calls - use this to show a count before deciding whether to spend API calls."""
    src_root = Path(repo_path) / "src" / "org" / "apache" / "pig"
    cache_dir = Path(cache_dir)
    candidates = file_paths if file_paths is not None else sorted(src_root.rglob("*.java"))
    return [p for p in candidates if _read_cache(cache_dir, src_root, p) is None]


def codebase_summary_chunks(
    repo_path: str | Path,
    cache_dir: str | Path,
    llm: LLMClient | None = None,
    file_paths: list[Path] | None = None,
    confirm: bool = False,
) -> list[Chunk]:
    """One chunk per main-source .java file (codebase_summaries context type). Only ever
    summarizes files that aren't already cached; if any uncached files are in scope, this raises
    unless confirm=True, so a full ~1088-file sweep can't happen by accident. Call
    pending_summary_files() first to see the count and decide."""
    repo_path = Path(repo_path)
    cache_dir = Path(cache_dir)
    src_root = repo_path / "src" / "org" / "apache" / "pig"
    file_paths = file_paths if file_paths is not None else sorted(src_root.rglob("*.java"))

    pending = [p for p in file_paths if _read_cache(cache_dir, src_root, p) is None]
    if pending:
        if not confirm:
            raise RuntimeError(
                f"{len(pending)} of {len(file_paths)} file(s) have no cached summary yet; "
                "call again with confirm=True to spend the LLM calls, or narrow file_paths first."
            )
        if llm is None:
            from src.llm.openai_client import OpenAIClient
            llm = OpenAIClient()
        for path in pending:
            summary = _summarize_file(llm, src_root, path)
            _write_cache(cache_dir, src_root, path, summary, llm.model)

    chunks: list[Chunk] = []
    for path in file_paths:
        cached = _read_cache(cache_dir, src_root, path)
        if not cached or not cached.get("summary"):
            continue
        rel = path.relative_to(src_root).as_posix()
        chunks.append(Chunk(
            id=f"codebase_summary::{rel}",
            text=cached["summary"],
            context_type=ContextType.CODEBASE_SUMMARIES,
            metadata={"file_path": rel},
        ))
    print(f"Built {len(chunks)} codebase-summary chunks")
    print(chunks[:5])
    return chunks
