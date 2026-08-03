"""Tests for codebase_summary_chunks: cache-first LLM summarization with a confirm gate. Uses a
fake LLMClient so no real API calls happen; verifies the gate, caching (no re-summarization once
cached), and the chunk shape.
"""

from pathlib import Path

import pytest

from src.conditions import ContextType
from src.llm.base import LLMClient, LLMResponse
from src.retrieval.sources import codebase_summary_chunks, pending_summary_files


class FakeLLMClient(LLMClient):
    def __init__(self):
        super().__init__(model="fake-model")
        self.calls: list[str] = []

    def _complete_once(self, prompt, system, **kwargs):
        self.calls.append(prompt)
        return LLMResponse(text=f"Summary of: {prompt.splitlines()[0]}", model=self.model)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    src_root = tmp_path / "src" / "org" / "apache" / "pig"
    src_root.mkdir(parents=True)
    (src_root / "Foo.java").write_text("package org.apache.pig;\npublic class Foo { void bar() {} }")
    (src_root / "Baz.java").write_text("package org.apache.pig;\npublic class Baz {}")
    return tmp_path


def test_pending_summary_files_lists_all_before_any_cache(repo, tmp_path):
    cache_dir = tmp_path / "cache"
    pending = pending_summary_files(repo, cache_dir)
    assert {p.name for p in pending} == {"Foo.java", "Baz.java"}


def test_raises_without_confirm_when_files_are_uncached(repo, tmp_path):
    cache_dir = tmp_path / "cache"
    llm = FakeLLMClient()
    with pytest.raises(RuntimeError, match=r"2 of 2"):
        codebase_summary_chunks(repo, cache_dir, llm=llm)
    assert llm.calls == []  # confirm gate must block the API call, not just warn


def test_confirm_true_summarizes_and_caches(repo, tmp_path):
    cache_dir = tmp_path / "cache"
    llm = FakeLLMClient()
    chunks = codebase_summary_chunks(repo, cache_dir, llm=llm, confirm=True)

    ids = {c.id for c in chunks}
    assert ids == {"codebase_summary::Foo.java", "codebase_summary::Baz.java"}
    for c in chunks:
        assert c.context_type is ContextType.CODEBASE_SUMMARIES
        assert c.text.startswith("Summary of:")
    assert len(llm.calls) == 2
    assert pending_summary_files(repo, cache_dir) == []


def test_second_call_reuses_cache_without_new_llm_calls(repo, tmp_path):
    cache_dir = tmp_path / "cache"
    llm = FakeLLMClient()
    codebase_summary_chunks(repo, cache_dir, llm=llm, confirm=True)
    assert len(llm.calls) == 2

    # No confirm needed, and no new calls, since everything is already cached.
    chunks = codebase_summary_chunks(repo, cache_dir, llm=llm, confirm=False)
    assert len(chunks) == 2
    assert len(llm.calls) == 2


def test_new_file_added_later_only_summarizes_the_new_one(repo, tmp_path):
    cache_dir = tmp_path / "cache"
    llm = FakeLLMClient()
    codebase_summary_chunks(repo, cache_dir, llm=llm, confirm=True)
    assert len(llm.calls) == 2

    (repo / "src" / "org" / "apache" / "pig" / "Qux.java").write_text(
        "package org.apache.pig;\npublic class Qux {}"
    )
    pending = pending_summary_files(repo, cache_dir)
    assert {p.name for p in pending} == {"Qux.java"}

    chunks = codebase_summary_chunks(repo, cache_dir, llm=llm, confirm=True)
    assert len(llm.calls) == 3  # only the new file triggered a call
    assert {c.metadata["file_path"] for c in chunks} == {"Foo.java", "Baz.java", "Qux.java"}
