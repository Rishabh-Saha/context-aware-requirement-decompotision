"""Chunking config (proposal Section 7.2): recursive character splitter, 500-char target with
50-char overlap, splitting on section and paragraph boundaries first. Thin wrapper so the numbers
live in one place and the LangChain dependency stays optional at import time."""

from __future__ import annotations

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
SEPARATORS = ["\n\n", "\n", ". ", " ", ""]   # section/paragraph boundaries favoured first


def make_splitter():
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # lazy

    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
    )
