"""ChromaDB index over all four context types in a single collection, each chunk tagged with its
context type so a single retrieval call can be filtered per ablation condition (proposal Section
7.2).

Build strategy (researcher decision, CLAUDE.md): past_tickets, design_documents, and
coding_conventions are embedded in full on the first build - they're cheap and static. codebase_
summaries is built incrementally into the SAME shared collection: a small bounded slice is enough
for the sanity run (dense_query against a partial codebase_summaries set is fine there), but the
real 120-generation run must refuse to start until the full main-source summary pass has landed,
enforced by assert_codebase_summaries_complete(). All writes use upsert, not add, so re-running a
build (sanity slice, then later the full pass) never errors on duplicate ids and never requires a
rebuild - it just adds what's missing.
"""

from __future__ import annotations

from src.conditions import ContextType
from src.retrieval.sources import Chunk

_EMBED_BATCH = 100


def _default_embed_fn(texts: list[str]) -> list[list[float]]:
    from src.llm.openai_client import embed_texts  # lazy: keeps the OpenAI SDK optional at import
    return embed_texts(texts)


class ContextIndex:
    def __init__(self, collection_name: str = "seoss_pig", persist_dir: str = "./data/chroma"):
        self.collection_name = collection_name
        self.persist_dir = persist_dir
        self._collection = None

    def _ensure(self):
        if self._collection is None:
            import chromadb
            client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = client.get_or_create_collection(self.collection_name)
        return self._collection

    def add(
        self,
        ids: list[str],
        texts: list[str],
        context_type: ContextType,
        embeddings=None,
        extra_metadata: list[dict] | None = None,
    ):
        """Low-level upsert: one context_type for the whole batch, with optional per-id extra
        metadata (e.g. issue_id, file_path) merged in. Upsert, not add, so calling this again with
        an id already present replaces it rather than raising."""
        col = self._ensure()
        extra_metadata = extra_metadata if extra_metadata is not None else [{} for _ in ids]
        metadatas = [{"context_type": context_type.value, **extra} for extra in extra_metadata]
        col.upsert(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)

    def add_chunks(self, chunks: list[Chunk], embed_fn=None) -> int:
        """Split each Chunk's text into the fixed 500/50 embed-ready pieces (chunking.py - the
        tested splitter, unchanged here), embed them in batches, and upsert into the collection.
        Returns the number of pieces written. Safe to call repeatedly with an overlapping or
        growing chunk list (e.g. a sanity slice of codebase_summaries followed later by the full
        corpus): existing piece ids are just overwritten with identical content, and new ones are
        added, without needing to rebuild anything."""
        from src.retrieval.chunking import make_splitter

        if not chunks:
            return 0
        splitter = make_splitter()
        embed_fn = embed_fn or _default_embed_fn

        ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict] = []
        for chunk in chunks:
            pieces = splitter.split_text(chunk.text)
            for i, piece in enumerate(pieces):
                ids.append(f"{chunk.id}::{i}")
                texts.append(piece)
                metadatas.append({"context_type": chunk.context_type.value, **chunk.metadata})

        col = self._ensure()
        for start in range(0, len(ids), _EMBED_BATCH):
            batch_texts = texts[start:start + _EMBED_BATCH]
            embeddings = embed_fn(batch_texts)
            col.upsert(
                ids=ids[start:start + _EMBED_BATCH],
                documents=batch_texts,
                metadatas=metadatas[start:start + _EMBED_BATCH],
                embeddings=embeddings,
            )
        return len(ids)

    def dense_query(
        self,
        query_embedding: list[float],
        active: tuple[ContextType, ...],
        top_k: int,
        exclude_issue_id: str | None = None,
    ):
        """Cosine-ranked candidates restricted to the active context types via metadata filter.
        exclude_issue_id additionally drops past_tickets chunks whose issue_id matches the
        requirement being decomposed, so a requirement can't retrieve itself; chunks with no
        issue_id (design_docs, coding_conventions, codebase_summaries) are unaffected."""
        if not active:
            # Empty $in is rejected by chromadb; vanilla (no active types) short-circuits to no
            # results without querying the collection at all.
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        col = self._ensure()
        type_filter = {"context_type": {"$in": [c.value for c in active]}}
        if exclude_issue_id:
            where = {"$and": [type_filter, {"issue_id": {"$ne": exclude_issue_id}}]}
        else:
            where = type_filter
        return col.query(query_embeddings=[query_embedding], n_results=top_k, where=where)

    def codebase_summary_coverage(self, total_files: int) -> tuple[int, int]:
        """(embedded_file_count, total_files): counts distinct file_path values already upserted
        under the codebase_summaries context type. Used to gate the full 120-generation run so
        'full RAG' can never run against a partially-summarized codebase."""
        col = self._ensure()
        got = col.get(where={"context_type": ContextType.CODEBASE_SUMMARIES.value})
        file_paths = {m.get("file_path") for m in got["metadatas"] if m.get("file_path")}
        return len(file_paths), total_files

    def assert_codebase_summaries_complete(self, total_files: int) -> None:
        """Hard gate for the real run (not the sanity run): raises unless every main-source file
        has a codebase_summaries chunk in the shared index. Always prints the coverage first."""
        covered, total = self.codebase_summary_coverage(total_files)
        print(f"codebase_summaries coverage: {covered}/{total} files embedded.")
        if covered < total:
            raise RuntimeError(
                f"codebase_summaries coverage is {covered}/{total} - the full run must not start "
                "until the full main-source summary pass has landed in the shared index. This is "
                "fine for the sanity run (partial codebase_summaries is expected there), but "
                "'full_rag' and the leave-one-out conditions would be invalid for the real 120-"
                "generation run against an incomplete codebase summary set."
            )

