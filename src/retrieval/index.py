"""ChromaDB index over all four context types in a single collection, each chunk tagged with its
context type so a single retrieval call can be filtered per ablation condition (proposal Section
7.2). Build logic is scaffolded; wire it to real chunk sources during Phase 1."""

from __future__ import annotations

from src.conditions import ContextType


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

    def add(self, ids: list[str], texts: list[str], context_type: ContextType, embeddings=None):
        col = self._ensure()
        metadatas = [{"context_type": context_type.value} for _ in ids]
        col.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)

    def dense_query(self, query_embedding: list[float], active: tuple[ContextType, ...], top_k: int):
        """Cosine-ranked candidates restricted to the active context types via metadata filter."""
        col = self._ensure()
        where = {"context_type": {"$in": [c.value for c in active]}} if active else None
        return col.query(query_embeddings=[query_embedding], n_results=top_k, where=where)
