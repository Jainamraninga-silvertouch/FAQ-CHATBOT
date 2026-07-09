"""
Product detection and FAQ document filtering.

Determines whether a question targets BatchSmart, LabelSmart, a comparison,
or a general multi-product query. Also identifies which uploaded files are
searchable FAQ content vs. internal/developer documents.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class ProductIntent(str, Enum):
    BATCHSMART = "BatchSmart"
    LABELSMART = "LabelSmart"
    COMPARE = "Compare"
    GENERAL = "General"
    UNKNOWN = "Unknown"


_NON_SEARCHABLE_PATTERNS = (
    re.compile(r"^readme", re.IGNORECASE),
    re.compile(r"installation", re.IGNORECASE),
    re.compile(r"developer", re.IGNORECASE),
    re.compile(r"upload.?instruction", re.IGNORECASE),
    re.compile(r"\blog\b", re.IGNORECASE),
    re.compile(r"dev.?note", re.IGNORECASE),
)

_MULTI_PRODUCT_PATTERNS = (
    "what products",
    "what solutions",
    "what do you offer",
    "what do you provide",
    "what ai products",
    "list of products",
    "all products",
    "all your products",
    "all your ai",
    "your products",
    "your solutions",
    "explain all",
    "both products",
    "each product",
    "products do you",
    "solutions do you",
)

_COMPARE_KEYWORDS = (
    "compare",
    "comparison",
    "difference between",
    "differences between",
    " versus ",
    " vs ",
    " vs.",
)

_AMBIGUOUS_PATTERNS = (
    "what does your software do",
    "what does your product do",
    "what does your platform do",
    "what does your solution do",
    "what does your tool do",
    "what does your system do",
    "what can your software do",
    "what can your product do",
    "what can your platform do",
)


def is_searchable_document(filename: str) -> bool:
    """Return True only for FAQ documents that should participate in search."""
    name_lower = filename.lower()

    for pattern in _NON_SEARCHABLE_PATTERNS:
        if pattern.search(name_lower):
            return False

    if "batchsmart" in name_lower or "labelsmart" in name_lower:
        return True
    if "faq" in name_lower:
        return True

    return False


def get_product_from_filename(filename: str) -> Optional[str]:
    """Map a filename to its product label, if known."""
    name_lower = filename.lower()
    if "batchsmart" in name_lower:
        return "BatchSmart"
    if "labelsmart" in name_lower:
        return "LabelSmart"
    return None


def _mentions_batchsmart(text: str) -> bool:
    return "batchsmart" in text or "batch smart" in text


def _mentions_labelsmart(text: str) -> bool:
    return "labelsmart" in text or "label smart" in text


def is_multi_product_question(question: str) -> bool:
    """True when the user explicitly wants information about all products."""
    q_lower = question.lower()
    return any(pattern in q_lower for pattern in _MULTI_PRODUCT_PATTERNS)


def _looks_ambiguous(question: str) -> bool:
    """Return True for broad questions that do not specify a product."""
    q_lower = question.lower().strip()
    if not q_lower or is_multi_product_question(question):
        return False

    if any(pattern in q_lower for pattern in _AMBIGUOUS_PATTERNS):
        return True

    generic_terms = ("software", "product", "solution", "platform", "tool", "system", "company")
    return any(term in q_lower for term in generic_terms) and "what" in q_lower and "do" in q_lower


def detect_product_intent(question: str) -> ProductIntent:
    """Classify the question as product-specific, comparative, general, or unknown."""
    q_lower = question.lower()

    has_batch = _mentions_batchsmart(q_lower)
    has_label = _mentions_labelsmart(q_lower)
    is_compare = any(kw in q_lower for kw in _COMPARE_KEYWORDS) and has_batch and has_label

    if is_compare:
        return ProductIntent.COMPARE
    if has_batch and not has_label:
        return ProductIntent.BATCHSMART
    if has_label and not has_batch:
        return ProductIntent.LABELSMART
    if is_multi_product_question(question):
        return ProductIntent.GENERAL
    if _looks_ambiguous(question):
        return ProductIntent.UNKNOWN
    return ProductIntent.GENERAL
