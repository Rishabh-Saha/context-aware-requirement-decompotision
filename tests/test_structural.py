from src.schema import Complexity, Decomposition, UserStory
from src.eval.structural import structural_metrics


def _story(sid, story, ac, deps=(), files=()):
    return UserStory(id=sid, story=story, acceptance_criteria=list(ac),
                     complexity=Complexity.M, dependencies=list(deps), source_files=list(files))


def test_metrics_basic():
    d = Decomposition(
        epic_summary="epic",
        user_stories=[
            _story("US-1", "As a user, I want export so that I can share.",
                   ["given x when y then z"], files=["src/org/apache/pig/Main.java"]),
            _story("US-2", "Refactor the loader.", [], deps=["US-1"], files=["the loader"]),
        ],
    )
    m = structural_metrics(d)
    assert m["num_user_stories"] == 2
    assert m["well_formedness_rate"] == 0.5          # only US-1 follows the template
    assert m["avg_acceptance_criteria"] == 0.5
    assert m["file_reference_specificity"] == 0.5     # US-1 cites a real path, US-2 is generic
    assert m["inter_story_dependency_rate"] == 0.5
    assert m["dangling_dependency_count"] == 0


def test_dangling_dependency_detected():
    d = Decomposition(epic_summary="e", user_stories=[
        _story("US-1", "As a user, I want x so that y.", [], deps=["US-99"]),
    ])
    assert structural_metrics(d)["dangling_dependency_count"] == 1


def test_empty_decomposition():
    d = Decomposition(epic_summary="e", user_stories=[])
    assert structural_metrics(d)["num_user_stories"] == 0
