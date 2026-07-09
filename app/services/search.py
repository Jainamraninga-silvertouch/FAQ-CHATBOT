"""
Retrieval service.

Defines a `Retriever` interface with a single `retrieve(query, top_k)`
method. Phase 1 ships `MemoryRetriever`, a BM25-based lexical search over
the in-memory store — no embeddings, no vector DB, no network calls.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from rank_bm25 import BM25Okapi

from app.services.memory_store import MemoryStore
from app.services.product_utils import get_product_from_filename, is_searchable_document

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

_STOP_WORDS = frozenset(
    {"a", "an", "the", "is", "are", "it", "can", "do", "does", "what", "how", "why", "who", "and", "or"}
)

_ABBREVIATION_EXPANSIONS = {
    "bmr": "batch manufacturing record",
    "mbr": "batch manufacturing record",
    "qa": "quality assurance",
    "gmp": "good manufacturing practice",
}

# Weak matches below this fraction of the top score are dropped.
_RELATIVE_SCORE_RATIO = 0.40
# Overlap weight when BM25 IDF degenerates on small corpora.
_OVERLAP_WEIGHT = 0.25


@dataclass
class RetrievedSection:
    document_id: str
    filename: str
    section: str
    text: str
    score: float


class Retriever(ABC):
    """Common interface every retrieval backend must implement."""

    @abstractmethod
    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        product_filter: Optional[str] = None,
        allow_multi_product: bool = True,
        overview_mode: bool = False,
    ) -> List[RetrievedSection]:
        ...


def _normalize_for_tokenization(text: str) -> str:
    normalized = text.lower()
    for abbreviation, expansion in _ABBREVIATION_EXPANSIONS.items():
        normalized = re.sub(rf"\b{abbreviation}\b", expansion, normalized)
    return normalized


def _tokenize(text: str) -> List[str]:
    return _TOKEN_PATTERN.findall(_normalize_for_tokenization(text))


def _narrow_to_dominant_product(sections: List[RetrievedSection]) -> List[RetrievedSection]:
    """Keep only the dominant product when results clearly cluster on one."""
    if len(sections) <= 1:
        return sections

    by_product: dict[str, list[RetrievedSection]] = {}
    for section in sections:
        product = get_product_from_filename(section.filename)
        if product:
            by_product.setdefault(product, []).append(section)

    if len(by_product) <= 1:
        return sections

    dominant = max(by_product, key=lambda p: (len(by_product[p]), by_product[p][0].score))
    dominant_sections = by_product[dominant]
    total = len(sections)

    if len(dominant_sections) >= max(2, int(total * 0.67)):
        return sorted(dominant_sections, key=lambda s: s.score, reverse=True)

    return sections


def _significant_query_terms(query_tokens: List[str]) -> List[str]:
    terms = [t for t in set(query_tokens) if t not in _STOP_WORDS and len(t) > 2]
    return terms if terms else list(set(query_tokens))


def _significant_overlap_count(tokens: List[str], query_tokens: List[str]) -> int:
    token_set = set(tokens)
    return sum(1 for t in _significant_query_terms(query_tokens) if t in token_set)


def _meaningful_overlap(tokens: List[str], query_tokens: List[str]) -> bool:
    return _significant_overlap_count(tokens, query_tokens) >= 1


class MemoryRetriever(Retriever):
    """
    BM25 lexical search over FAQ sections held in MemoryStore.
    Supports product filtering and excludes non-FAQ developer documents.
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        product_filter: Optional[str] = None,
        allow_multi_product: bool = True,
        overview_mode: bool = False,
    ) -> List[RetrievedSection]:
        if overview_mode:
            return self._retrieve_product_overviews(top_k)

        corpus_entries: List[RetrievedSection] = []
        tokenized_corpus: List[List[str]] = []

        for document in self._store.all_documents():
            if not is_searchable_document(document.filename):
                continue

            doc_product = get_product_from_filename(document.filename)
            if product_filter and doc_product != product_filter:
                continue

            for section in document.content:
                combined = f"{section.section} {section.text}"
                corpus_entries.append(
                    RetrievedSection(
                        document_id=document.document_id,
                        filename=document.filename,
                        section=section.section,
                        text=section.text,
                        score=0.0,
                    )
                )
                tokenized_corpus.append(_tokenize(combined))

        if not tokenized_corpus:
            return []

        query_tokens = _tokenize(query)
        bm25 = BM25Okapi(tokenized_corpus)
        bm25_scores = bm25.get_scores(query_tokens)

        query_text = " ".join(query_tokens)
        for entry, bm25_score, tokens in zip(corpus_entries, bm25_scores, tokenized_corpus):
            overlap = _significant_overlap_count(tokens, query_tokens)
            product = get_product_from_filename(entry.filename)
            product_bonus = 0.0
            if product_filter and product == product_filter:
                product_bonus += 1.5
            elif product_filter and product and product != product_filter:
                product_bonus -= 2.0
            if product and product.lower() in query_text:
                product_bonus += 0.75
            if product and product.lower() in " ".join(tokens):
                product_bonus += 0.25
            entry.score = float(bm25_score) + _OVERLAP_WEIGHT * overlap + product_bonus

        ranked = sorted(corpus_entries, key=lambda e: e.score, reverse=True)
        top_score = ranked[0].score
        top_overlap = max(
            _significant_overlap_count(tokens, query_tokens)
            for tokens in tokenized_corpus
        )

        relevant: List[RetrievedSection] = []
        for entry, tokens in zip(corpus_entries, tokenized_corpus):
            overlap = _significant_overlap_count(tokens, query_tokens)
            product = get_product_from_filename(entry.filename)
            if product_filter and product and product != product_filter:
                continue
            if overlap < 1:
                continue

            # On small corpora BM25 IDF can be zero; rely on overlap count instead.
            if top_score <= 0:
                min_overlap = max(2, top_overlap - 1) if top_overlap >= 3 else max(1, top_overlap)
                if overlap >= min_overlap:
                    relevant.append(entry)
                continue

            min_score = top_score * _RELATIVE_SCORE_RATIO
            if entry.score >= min_score:
                relevant.append(entry)

        relevant.sort(key=lambda e: e.score, reverse=True)

        if not allow_multi_product and not product_filter:
            relevant = _narrow_to_dominant_product(relevant)

        return relevant[:top_k]

    def _retrieve_product_overviews(self, top_k: int) -> List[RetrievedSection]:
        """Return the best introductory section from each product FAQ."""
        results: List[RetrievedSection] = []
        seen_products: set[str] = set()

        for document in self._store.all_documents():
            if not is_searchable_document(document.filename):
                continue

            product = get_product_from_filename(document.filename)
            if not product or product in seen_products:
                continue
            seen_products.add(product)

            chosen = document.content[0] if document.content else None
            for section in document.content:
                heading = section.section.lower()
                preview = section.text.lower()[:120]
                if product.lower() in preview or "overview" in heading or heading.startswith("what"):
                    chosen = section
                    break

            if chosen:
                results.append(
                    RetrievedSection(
                        document_id=document.document_id,
                        filename=document.filename,
                        section=chosen.section,
                        text=chosen.text,
                        score=1.0,
                    )
                )

        return results[:top_k]
