"""Tests for the Layer 3 judge pass (src/eval/judge.py and scripts/run_judge.py).

No network. The judge is a stub whose answers are chosen to exercise the parts that carry a
methodological decision rather than orchestration: the strictness of the verdict parse, the
translation of positional A/B answers back to sides across the two presentation orders, what
happens when the orders disagree, that a resumed pass spends nothing, and that no condition or
reference label ever reaches the judge prompt.
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

from src.conditions import Condition
from src.eval.comparisons import REFERENCE
from src.eval.judge import JudgeVerdict, parse_judge_response, render_judge_prompt
from src.llm.base import LLMResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_judge  # noqa: E402

PROMPT_TEMPLATE = Path("prompts/judge_pairwise.txt").read_text(encoding="utf-8")

# Markers a content-driven stub judge looks for, so its choice follows the text rather than the
# position and the two presentation orders therefore agree. Two are needed because one comparison
# type (vanilla against the reference) puts no generated marker on either side, and a stub with no
# opinion there would fall back to position and manufacture an inconsistency the runner is not
# responsible for.
MARKER = "distinctive-acceptance-detail"
REF_MARKER = "distinctive-prior-artefact-detail"


def decomposition(marker: str = "") -> dict:
    return {
        "epic_summary": f"Set the job name from the script file name {marker}".strip(),
        "user_stories": [
            {
                "id": "US-1",
                "story": "As a user, I want the job name set from the script, so that runs are identifiable.",
                "acceptance_criteria": [f"the job name matches the script name {marker}".strip()],
                "complexity": "M",
                "dependencies": [],
                "source_files": ["src/org/apache/pig/PigServer.java"],
            },
        ],
    }


class StubJudge:
    """Records every prompt it is shown and answers by a caller-supplied rule."""

    def __init__(self, rule):
        self.rule = rule
        self.prompts: list[str] = []

    def complete(self, prompt: str, system: str | None = None, **kwargs) -> LLMResponse:
        self.prompts.append(prompt)
        return LLMResponse(text=self.rule(prompt, len(self.prompts)), model="stub-judge")


def verdict_json(choice: str) -> str:
    payload = {c: choice for c in ("actionability", "completeness", "project_specificity",
                                   "granularity", "clarity")}
    payload["winner"] = choice
    payload["rationale"] = "stub"
    return json.dumps(payload)


def sides_shown(prompt: str) -> tuple[str, str]:
    """The two output blocks exactly as the judge sees them."""
    a_block, b_block = prompt.split("OUTPUT A:")[1].split("OUTPUT B:")
    return a_block, b_block


def content_rule(prompt: str, _n: int) -> str:
    """Pick whichever side carries the stronger marker, regardless of where it is shown. A judge
    behaving this way is positionally stable, so both orders must reconcile to the same side."""
    a_block, b_block = sides_shown(prompt)
    for marker in (MARKER, REF_MARKER):
        if marker in a_block:
            return verdict_json("A")
        if marker in b_block:
            return verdict_json("B")
    raise AssertionError("stub judge saw neither marker, so the fixture is not exercising content")


def always_a(_prompt: str, _n: int) -> str:
    """Pure positional bias: the first-shown side always wins, so the two orders must disagree."""
    return verdict_json("A")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    """A generation run on disk with the six conditions for two requirements, plus the config and
    frozen requirements the judge pass reads."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "judge_pairwise.txt").write_text(PROMPT_TEMPLATE, encoding="utf-8")

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump({
        "llm": {
            "generator": {"provider": "openai", "model": "gpt-4o", "temperature": 0.0},
            "judge": {"provider": "anthropic", "model": "claude-sonnet-4-6", "temperature": 0.0},
        },
        "eval": {"judge": {"criteria": list(run_judge.CRITERIA)}},
    }))

    issues = ["PIG-692", "PIG-704"]
    frozen = [{"_meta": {"frozen_at": "2026-01-01T00:00:00+00:00"}}]
    for issue in issues:
        frozen.append({
            "issue_key": issue,
            "title": "set up job name based on the file name",
            "description": "Right now the default job name is used when running a script.",
            "reference_artefacts": [f"Use the script name as the default job name, {REF_MARKER}."],
        })
    frozen_path = tmp_path / "data" / "frozen" / "requirements.json"
    frozen_path.parent.mkdir(parents=True)
    frozen_path.write_text(json.dumps(frozen))

    run_dir = tmp_path / "data" / "runs" / "RUN1"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": "RUN1",
        "generator": {"provider": "openai", "model": "gpt-4o", "temperature": 0.0},
        "requirements": issues,
    }))
    for issue in issues:
        for condition in Condition:
            # full_rag carries the marker, so the content-driven stub judge has a stable preference.
            marker = MARKER if condition is Condition.FULL_RAG else ""
            (run_dir / f"{issue}__{condition.value}.json").write_text(json.dumps({
                "run_id": "RUN1",
                "issue_key": issue,
                "condition": condition.value,
                "decomposition": decomposition(marker),
            }))
    return tmp_path


def run_pass(monkeypatch, stub: StubJudge, *extra: str) -> int:
    monkeypatch.setattr(run_judge, "make_judge", lambda cfg: stub)
    monkeypatch.setattr(sys, "argv", ["run_judge.py", "--run-id", "RUN1", *extra])
    return run_judge.main()


def judgments(workspace: Path) -> list[dict]:
    path = workspace / "data" / "runs" / "RUN1" / "judge" / "judgments.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- parsing

def test_parses_plain_and_fenced_verdicts():
    plain = parse_judge_response(verdict_json("B"))
    assert plain.winner == "B"
    assert plain.per_criterion["clarity"] == "B"

    fenced = parse_judge_response(f"```json\n{verdict_json('A')}\n```")
    assert fenced.winner == "A"
    assert set(fenced.per_criterion) == set(run_judge.CRITERIA)


def test_parse_is_strict_about_missing_and_invalid_choices():
    payload = json.loads(verdict_json("A"))

    missing = dict(payload)
    del missing["granularity"]
    with pytest.raises(ValueError, match="granularity"):
        parse_judge_response(json.dumps(missing))

    tie = dict(payload, clarity="tie")
    with pytest.raises(ValueError, match="clarity"):
        parse_judge_response(json.dumps(tie))

    no_winner = dict(payload)
    del no_winner["winner"]
    with pytest.raises(ValueError, match="winner"):
        parse_judge_response(json.dumps(no_winner))

    with pytest.raises(ValueError, match="not JSON"):
        parse_judge_response("the first one is better")


def test_side_of_translates_positional_answers():
    # In the BA presentation the sides are swapped, so the same "A" means the other side.
    assert run_judge.side_of("A", "vanilla", "full_rag") == "vanilla"
    assert run_judge.side_of("A", "full_rag", "vanilla") == "full_rag"


# ---------------------------------------------------------------- blindness

def test_judge_prompt_carries_no_condition_or_reference_labels(workspace, monkeypatch):
    stub = StubJudge(content_rule)
    assert run_pass(monkeypatch, stub) == 0
    assert stub.prompts

    # Condition names must not appear anywhere at all. The rest of the forbidden list is checked
    # only against the substituted region (requirement plus the two outputs), because the template's
    # own project_specificity criterion legitimately contains the word "references" and that fixed
    # wording tells the judge nothing about which side is which.
    provenance_tokens = [REFERENCE, "reference_artefacts", "RUN1", "condition", "ablation",
                         "human", "ground truth", "baseline"]
    for prompt in stub.prompts:
        for condition in Condition:
            assert condition.value not in prompt, f"{condition.value!r} leaked into the judge prompt"
        substituted = prompt.split("REQUIREMENT:")[1].split("Compare A and B")[0].lower()
        for token in provenance_tokens:
            assert token not in substituted, f"{token!r} leaked into the judge prompt"
        # The only side labels the judge ever sees.
        assert "OUTPUT A:" in prompt and "OUTPUT B:" in prompt


def test_reference_artefacts_are_scrubbed_of_provenance():
    """The real frozen artefacts are issue descriptions plus commit messages, and the commit
    messages arrive with an svn trailer and the issue key prefixing the subject. Both would tell the
    judge which side came from project history rather than from a model."""
    artefact = (
        "PIG-692 When running a job from a script, use that script name as the default job name.\n"
        "\n"
        "\n"
        "\n"
        "git-svn-id: https://svn.apache.org/repos/asf/hadoop/pig/trunk@123 13f79535\n"
        "Signed-off-by: A Committer <c@apache.org>\n"
    )
    scrubbed = run_judge.scrub_artefact(artefact, "PIG-692")

    assert scrubbed == "When running a job from a script, use that script name as the default job name."
    assert "git-svn-id" not in scrubbed
    assert "Signed-off-by" not in scrubbed
    assert "PIG-692" not in scrubbed


def test_scrub_leaves_requirement_prose_alone():
    prose = "When running pig script from command like like this:\n\npig scriptfile\n\nright now."
    assert run_judge.scrub_artefact(prose, "PIG-692") == prose


def test_render_judge_prompt_survives_braces_in_the_outputs():
    rendered = render_judge_prompt("req", "left {not a field}", "right {}", PROMPT_TEMPLATE)
    assert "left {not a field}" in rendered and "right {}" in rendered


# ---------------------------------------------------------------- reconciliation

def test_content_stable_judge_reconciles_to_a_winner(workspace, monkeypatch):
    assert run_pass(monkeypatch, StubJudge(content_rule)) == 0
    rows = judgments(workspace)

    assert len(rows) == 14                       # 2 requirements x 7 comparison types
    assert all(not r["positional_inconsistent"] for r in rows)
    sq1 = [r for r in rows if r["sub_question"] == "SQ1"]
    assert len(sq1) == 8
    # full_rag is the marked side in every SQ1 and SQ2 comparison, so it wins each of them.
    assert all(r["winner"] == Condition.FULL_RAG.value for r in sq1)
    assert all(r["per_criterion_winner"]["clarity"] == Condition.FULL_RAG.value for r in sq1)
    assert all(r["per_criterion_inconsistent"] == [] for r in sq1)

    # SQ3 resolves by content in both directions: the marked generation beats the reference, and
    # the unmarked one loses to it. Winners are recorded as side names, not as A or B.
    sq3 = {(r["left"], r["right"]): r["winner"] for r in rows if r["sub_question"] == "SQ3"}
    assert sq3[(Condition.FULL_RAG.value, REFERENCE)] == Condition.FULL_RAG.value
    assert sq3[(Condition.VANILLA.value, REFERENCE)] == REFERENCE


def test_positionally_biased_judge_is_marked_inconsistent(workspace, monkeypatch):
    assert run_pass(monkeypatch, StubJudge(always_a)) == 0
    rows = judgments(workspace)

    assert len(rows) == 14
    assert all(r["positional_inconsistent"] for r in rows)
    assert all(r["winner"] is None for r in rows)
    assert all(r["per_criterion_winner"][c] is None for r in rows for c in run_judge.CRITERIA)
    # The raw record still keeps what each order actually said, so the bias stays auditable.
    for row in rows:
        assert row["ab_winner_side"] != row["ba_winner_side"]


def test_both_orders_are_judged_and_archived_raw(workspace, monkeypatch):
    assert run_pass(monkeypatch, StubJudge(content_rule)) == 0
    raw_path = workspace / "data" / "runs" / "RUN1" / "judge" / "judgments_raw.jsonl"
    raw = [json.loads(line) for line in raw_path.read_text().splitlines() if line.strip()]

    assert len(raw) == 28                        # 14 comparisons x 2 presentation orders
    assert {r["presentation"] for r in raw} == {"AB", "BA"}
    for row in raw:
        assert row["winner_side"] in (row["shown_a"], row["shown_b"])
    # The reference side is compared against both full RAG and vanilla, in both orders.
    reference_rows = [r for r in raw if REFERENCE in (r["shown_a"], r["shown_b"])]
    assert len(reference_rows) == 8
    assert all(r["sub_question"] == "SQ3" for r in reference_rows)


# ---------------------------------------------------------------- resume, limit, failures

def test_resume_skips_already_judged_comparisons(workspace, monkeypatch):
    first = StubJudge(content_rule)
    assert run_pass(monkeypatch, first) == 0
    assert len(first.prompts) == 28

    second = StubJudge(content_rule)
    assert run_pass(monkeypatch, second) == 0
    assert second.prompts == [], "a resumed pass must not re-pay for judged comparisons"
    assert len(judgments(workspace)) == 14, "resume must not duplicate reconciled rows"


def test_limit_restricts_to_the_first_requirements(workspace, monkeypatch):
    stub = StubJudge(content_rule)
    assert run_pass(monkeypatch, stub, "--limit", "1") == 0
    rows = judgments(workspace)
    assert len(rows) == 7
    assert {r["issue_key"] for r in rows} == {"PIG-692"}


def test_a_bad_verdict_is_recorded_and_the_pass_continues(workspace, monkeypatch):
    def break_the_third_call(prompt: str, n: int) -> str:
        return "not json at all" if n == 3 else content_rule(prompt, n)

    # A failure is a non-zero exit so a scripted run notices, but the other comparisons still land.
    assert run_pass(monkeypatch, StubJudge(break_the_third_call)) == 1
    judge_dir = workspace / "data" / "runs" / "RUN1" / "judge"
    failures = [json.loads(line) for line in
                (judge_dir / "failures.jsonl").read_text().splitlines() if line.strip()]

    assert len(failures) == 1
    assert "ValueError" in failures[0]["error"]
    assert len(judgments(workspace)) == 13, "only the failed comparison is missing"
    # Re-running retries exactly the failed comparison and nothing else.
    retry = StubJudge(content_rule)
    assert run_pass(monkeypatch, retry) == 0
    assert len(retry.prompts) == 2
    assert len(judgments(workspace)) == 14


def test_same_family_judge_is_refused(workspace, monkeypatch):
    cfg_path = workspace / "config" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["llm"]["judge"] = {"provider": "openai", "model": "gpt-4o", "temperature": 0.0}
    cfg_path.write_text(yaml.safe_dump(cfg))

    with pytest.raises(SystemExit, match="different model family"):
        run_pass(monkeypatch, StubJudge(content_rule))


def test_manifest_records_the_judge_configuration(workspace, monkeypatch):
    assert run_pass(monkeypatch, StubJudge(content_rule)) == 0
    manifest = json.loads(
        (workspace / "data" / "runs" / "RUN1" / "judge" / "manifest.json").read_text()
    )

    assert manifest["generation_run_id"] == "RUN1"
    assert manifest["judge"] == {"provider": "anthropic", "model": "claude-sonnet-4-6",
                                 "temperature": 0.0}
    assert manifest["generator"]["model"] == "gpt-4o"
    assert manifest["criteria"] == list(run_judge.CRITERIA)
    assert manifest["n_comparisons"] == 14 and manifest["n_ordered_judgements"] == 28


def test_missing_decomposition_is_a_failure_not_a_silent_skip(workspace, monkeypatch):
    (workspace / "data" / "runs" / "RUN1" / "PIG-692__vanilla.json").unlink()
    assert run_pass(monkeypatch, StubJudge(content_rule)) == 1

    judge_dir = workspace / "data" / "runs" / "RUN1" / "judge"
    failures = [json.loads(line) for line in
                (judge_dir / "failures.jsonl").read_text().splitlines() if line.strip()]
    # vanilla appears in three of the seven comparison types (SQ2 once, SQ3 once, and never in SQ1).
    assert {(f["left"], f["right"]) for f in failures} == {
        (Condition.VANILLA.value, Condition.FULL_RAG.value),
        (Condition.VANILLA.value, REFERENCE),
    }
    assert all("FileNotFoundError" in f["error"] for f in failures)


def test_judge_verdict_dataclass_defaults():
    v = JudgeVerdict(winner="A", per_criterion={c: "A" for c in run_judge.CRITERIA})
    assert v.rationale == ""
