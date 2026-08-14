"""Tests for scripts/run_experiment.py.

The parts worth testing here are the ones that carry a decision rather than orchestration over
already-tested modules: what a diagnostics row promises about itself, and above all the resume
path. Resume is the expensive thing to get wrong, since a bug there means re-paying for
generations that are already sitting on disk, so it gets an end-to-end test with a counting stub
generator that asserts the second run spends nothing.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.conditions import Condition
from src.eval.file_verifier import FileVerifier
from src.pipeline.generate import run_condition
from src.schema import Decomposition

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_experiment  # noqa: E402

DECOMP_JSON = {
    "epic_summary": "Add a hash function",
    "user_stories": [
        {
            "id": "US-1",
            "story": "As a user, I want two HashFNV versions, so that casts are implicit.",
            "acceptance_criteria": ["one arg works", "two args work"],
            "complexity": "M",
            "dependencies": [],
            "source_files": ["src/org/apache/pig/PigServer.java", "does/not/Exist.java"],
        },
        {
            "id": "US-2",
            "story": "Update the docs.",
            "acceptance_criteria": ["docs mention both versions"],
            "complexity": "S",
            "dependencies": ["US-1"],
            "source_files": ["impl/PigContext.java"],
        },
    ],
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway Pig-shaped clone, the same fixture pattern the file verifier tests use."""
    root = tmp_path / "pig"
    root.mkdir()

    def git(*a):
        subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t.dev")
    git("config", "user.name", "t")
    for rel in ["src/org/apache/pig/PigServer.java", "src/org/apache/pig/impl/PigContext.java"]:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("// stub\n")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    return root


@pytest.fixture
def decomp() -> Decomposition:
    return Decomposition.model_validate(DECOMP_JSON)


class StubLLM:
    """Counts calls, so a test can assert that a resumed run generated nothing."""

    def __init__(self, text: str):
        self.text = text
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, prompt, system=None, **kwargs):
        from src.llm.base import LLMResponse
        self.calls += 1
        self.prompts.append(prompt)
        return LLMResponse(text=self.text, model="stub-model")


class ExplodingIndex:
    """Any retrieval call is a failure, which is how the prompt= passthrough gets proven."""

    def chunks_for_types(self, active):
        raise AssertionError("retrieval must not run when prompt= is supplied")

    def dense_query(self, *a, **kw):
        raise AssertionError("retrieval must not run when prompt= is supplied")


# -- run_condition prompt passthrough --------------------------------------------------------

def test_run_condition_with_prompt_skips_retrieval():
    llm = StubLLM(json.dumps(DECOMP_JSON))
    requirement = {"issue_key": "PIG-1", "title": "t", "description": "d"}

    result = run_condition(
        requirement, Condition.FULL_RAG, ExplodingIndex(), loader=None, llm=llm,
        prompt="PRE-ASSEMBLED PROMPT",
    )

    assert isinstance(result, Decomposition)
    assert llm.calls == 1
    # The archived prompt has to be the prompt that was actually sent, not a re-assembled twin.
    assert llm.prompts == ["PRE-ASSEMBLED PROMPT"]


# -- pure helpers ----------------------------------------------------------------------------

def test_frozen_requirements_drops_meta(tmp_path: Path):
    path = tmp_path / "requirements.json"
    path.write_text(json.dumps([
        {"_meta": {"target_n": 20}},
        {"issue_key": "PIG-704", "title": "t", "description": "d"},
    ]))
    reqs = run_experiment.frozen_requirements(path)
    assert [r["issue_key"] for r in reqs] == ["PIG-704"]


def test_cell_paths_are_issue_and_condition(tmp_path: Path):
    decomp_path, prompt_path = run_experiment.cell_paths(tmp_path, "PIG-704", Condition.FULL_RAG)
    assert decomp_path.name == "PIG-704__full_rag.json"
    assert prompt_path.name == "PIG-704__full_rag.prompt.txt"


def test_source_file_references_keeps_duplicates(decomp):
    refs = run_experiment.source_file_references(decomp)
    assert refs == [
        "src/org/apache/pig/PigServer.java",
        "does/not/Exist.java",
        "impl/PigContext.java",
    ]


def test_existing_diagnostic_keys(tmp_path: Path):
    path = tmp_path / "diagnostics.jsonl"
    path.write_text(
        json.dumps({"run_id": "r", "issue_key": "PIG-1", "condition": "vanilla"}) + "\n"
        + json.dumps({"run_id": "r", "issue_key": "PIG-1", "condition": "full_rag"}) + "\n"
    )
    assert run_experiment.existing_diagnostic_keys(path) == {
        ("PIG-1", "vanilla"), ("PIG-1", "full_rag"),
    }


def test_existing_diagnostic_keys_missing_file(tmp_path: Path):
    assert run_experiment.existing_diagnostic_keys(tmp_path / "nope.jsonl") == set()


# -- diagnostics rows ------------------------------------------------------------------------

def test_diagnostics_row_is_self_describing(repo, decomp):
    row = run_experiment.diagnostics_row(
        "run-1", "PIG-704", Condition.NO_DESIGN_DOCS, decomp, FileVerifier(repo),
        {"model": "gpt-4o", "temperature": 0.0}, summaries_incomplete=False,
    )
    assert row["run_id"] == "run-1"
    assert row["issue_key"] == "PIG-704"
    assert row["condition"] == "full_rag_minus_design_documents"
    assert row["generator_model"] == "gpt-4o"
    assert row["generator_temperature"] == 0.0
    assert row["summaries_incomplete"] is False


def test_diagnostics_row_layers(repo, decomp):
    row = run_experiment.diagnostics_row(
        "run-1", "PIG-704", Condition.FULL_RAG, decomp, FileVerifier(repo),
        {"model": "gpt-4o", "temperature": 0.0}, summaries_incomplete=False,
    )
    assert row["layer1"]["num_user_stories"] == 2
    assert row["layer1"]["well_formedness_rate"] == 0.5   # US-2 is not templated
    # PigServer REAL, Exist.java HALLUCINATED, partial PigContext path AMBIGUOUS.
    assert row["layer2"]["counts"] == {"REAL": 1, "AMBIGUOUS": 1, "HALLUCINATED": 1}
    assert row["layer2"]["total"] == 3
    assert row["layer2"]["unique_references"] == 3


def test_diagnostics_row_layer2_null_without_anchors(decomp):
    """An absent Layer 2 measurement is null, not a zero that would read as perfect grounding."""
    row = run_experiment.diagnostics_row(
        "run-1", "PIG-704", Condition.VANILLA, decomp, None,
        {"model": "gpt-4o", "temperature": 0.0}, summaries_incomplete=True,
    )
    assert row["layer2"] is None
    assert row["summaries_incomplete"] is True


def test_build_verifier_without_local_commits_returns_none(repo):
    assert run_experiment.build_verifier(repo, {"issue_key": "PIG-1", "local_commits": []}, 2, 2) is None


# -- end to end, including resume ------------------------------------------------------------

class StubIndex:
    def __init__(self, covered: int, total: int):
        self._covered, self._total = covered, total

    def codebase_summary_coverage(self, total_files: int):
        return self._covered, self._total

    def assert_codebase_summaries_complete(self, total_files: int):
        raise RuntimeError("codebase_summaries coverage is incomplete")


class StubLoader:
    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def experiment(tmp_path: Path, repo: Path, monkeypatch):
    """Wire run_experiment.main() to local stubs: no network, no ChromaDB, no SEOSS db.

    Retrieval and index construction are covered by their own tests, so they are stubbed out here
    and what remains under test is the runner's own control flow.
    """
    config = tmp_path / "config.yaml"
    config.write_text(
        "llm:\n"
        "  generator:\n"
        "    provider: openai\n"
        "    model: gpt-4o\n"
        "    temperature: 0.3\n"
        "eval:\n"
        "  file_verifier:\n"
        "    commit_window_before: 2\n"
        "    commit_window_after: 2\n"
    )
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    frozen = tmp_path / "requirements.json"
    frozen.write_text(json.dumps([
        {"_meta": {"target_n": 20}},
        {"issue_key": "PIG-704", "title": "t1", "description": "d1", "local_commits": [head]},
        {"issue_key": "PIG-907", "title": "t2", "description": "d2", "local_commits": [head]},
    ]))

    llm = StubLLM(json.dumps(DECOMP_JSON))
    index = StubIndex(covered=5, total=10)
    monkeypatch.setattr(run_experiment, "ContextIndex", lambda **kw: index)
    monkeypatch.setattr(run_experiment, "SeossLoader", StubLoader)
    monkeypatch.setattr(run_experiment, "make_llm", lambda cfg: llm)
    monkeypatch.setattr(
        run_experiment, "build_condition_prompt",
        lambda req, cond, idx, loader, per_type=2: f"PROMPT {req['issue_key']} {cond.value}",
    )

    def run(*extra: str) -> int:
        argv = [
            "run_experiment.py",
            "--config", str(config),
            "--frozen", str(frozen),
            "--repo", str(repo),
            "--db", str(tmp_path / "unused.sqlite"),
            "--runs-dir", str(tmp_path / "runs"),
            "--run-id", "testrun",
            *extra,
        ]
        monkeypatch.setattr(sys, "argv", argv)
        return run_experiment.main()

    return type("Experiment", (), {
        "run": staticmethod(run), "llm": llm, "run_dir": tmp_path / "runs" / "testrun",
    })


def test_limit_runs_six_cells_for_one_requirement(experiment):
    assert experiment.run("--limit", "1") == 0
    assert experiment.llm.calls == 6
    files = sorted(p.name for p in experiment.run_dir.glob("PIG-*.json"))
    assert len(files) == 6
    assert "PIG-704__vanilla.json" in files
    assert not list(experiment.run_dir.glob("PIG-907*"))


def test_prompt_archived_next_to_each_generation(experiment):
    experiment.run("--limit", "1")
    prompt = (experiment.run_dir / "PIG-704__full_rag.prompt.txt").read_text()
    assert prompt == "PROMPT PIG-704 full_rag"
    # The prompt sent to the generator is the one on disk, not a re-assembled copy.
    assert prompt in experiment.llm.prompts
    payload = json.loads((experiment.run_dir / "PIG-704__full_rag.json").read_text())
    assert payload["prompt_file"] == "PIG-704__full_rag.prompt.txt"


def test_diagnostics_one_row_per_cell(experiment):
    experiment.run("--limit", "1")
    rows = [json.loads(line) for line in
            (experiment.run_dir / "diagnostics.jsonl").read_text().splitlines() if line.strip()]
    assert len(rows) == 6
    assert {r["condition"] for r in rows} == {c.value for c in Condition}
    assert all(r["run_id"] == "testrun" and r["issue_key"] == "PIG-704" for r in rows)
    assert all(r["layer2"]["total"] == 3 for r in rows)


def test_resume_regenerates_nothing(experiment):
    experiment.run("--limit", "1")
    assert experiment.llm.calls == 6

    assert experiment.run("--limit", "1") == 0
    assert experiment.llm.calls == 6, "a resumed run must not re-pay for existing generations"

    rows = [json.loads(line) for line in
            (experiment.run_dir / "diagnostics.jsonl").read_text().splitlines() if line.strip()]
    assert len(rows) == 6, "diagnostics rows must not be duplicated on resume"


def test_resume_rescores_a_generation_that_was_never_scored(experiment):
    """The crash window between writing a decomposition and appending its row. The generation is
    already paid for, so it must be reloaded and scored rather than regenerated."""
    experiment.run("--limit", "1")
    diagnostics = experiment.run_dir / "diagnostics.jsonl"
    rows = [json.loads(line) for line in diagnostics.read_text().splitlines() if line.strip()]
    diagnostics.write_text("".join(json.dumps(r) + "\n" for r in rows[:-1]))

    assert experiment.run("--limit", "1") == 0
    assert experiment.llm.calls == 6
    rows_after = [json.loads(line) for line in diagnostics.read_text().splitlines() if line.strip()]
    assert len(rows_after) == 6


def test_temperature_from_config_is_recorded(experiment):
    experiment.run("--limit", "1")
    manifest = json.loads((experiment.run_dir / "manifest.json").read_text())
    assert manifest["generator"] == {"provider": "openai", "model": "gpt-4o", "temperature": 0.3}
    payload = json.loads((experiment.run_dir / "PIG-704__vanilla.json").read_text())
    assert payload["generator"]["temperature"] == 0.3


def test_incomplete_summaries_stamped_everywhere(experiment):
    """A knowingly incomplete run has to be impossible to mistake for a clean one later."""
    experiment.run("--allow-incomplete-summaries")
    manifest = json.loads((experiment.run_dir / "manifest.json").read_text())
    assert manifest["summaries_incomplete"] is True

    payload = json.loads((experiment.run_dir / "PIG-907__full_rag.json").read_text())
    assert payload["summaries_incomplete"] is True

    rows = [json.loads(line) for line in
            (experiment.run_dir / "diagnostics.jsonl").read_text().splitlines() if line.strip()]
    assert len(rows) == 12
    assert all(r["summaries_incomplete"] is True for r in rows)


def test_full_run_blocked_by_incomplete_summaries(experiment):
    with pytest.raises(RuntimeError, match="coverage is incomplete"):
        experiment.run()


def test_failed_generation_does_not_stop_the_run(experiment, monkeypatch):
    """One malformed response must not cost the other cells, and must leave nothing behind, so a
    later resume retries exactly that cell."""
    original = experiment.llm.complete

    def flaky(prompt, system=None, **kwargs):
        if "full_rag_minus_design_documents" in prompt:
            from src.llm.base import LLMResponse
            experiment.llm.calls += 1
            return LLMResponse(text="not json at all", model="stub-model")
        return original(prompt, system, **kwargs)

    monkeypatch.setattr(experiment.llm, "complete", flaky)

    assert experiment.run("--limit", "1") == 1   # non-zero exit flags the failure
    assert len(list(experiment.run_dir.glob("PIG-704__*.json"))) == 5
    assert not (experiment.run_dir / "PIG-704__full_rag_minus_design_documents.json").exists()

    failures = [json.loads(line) for line in
                (experiment.run_dir / "failures.jsonl").read_text().splitlines() if line.strip()]
    assert len(failures) == 1
    assert failures[0]["condition"] == "full_rag_minus_design_documents"

    monkeypatch.setattr(experiment.llm, "complete", original)
    assert experiment.run("--limit", "1") == 0
    assert (experiment.run_dir / "PIG-704__full_rag_minus_design_documents.json").exists()
