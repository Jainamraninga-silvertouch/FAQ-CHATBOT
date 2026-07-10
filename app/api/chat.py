"""
Chat API: POST /chat

Retrieves relevant sections, builds the strict context-only prompt, calls
the LLM, and returns the answer along with the sources used.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.schemas import ChatRequest, ChatResponse, SourceSnippet
from app.services.memory_store import MemoryStore, get_memory_store
from app.services.search import MemoryRetriever, Retriever
from app.services.prompt_builder import NO_ANSWER_MESSAGE, build_messages, parse_answer_and_questions
from app.services.llm_client import (
    LLMConfigurationError,
    LLMRequestTooLargeError,
    generate_answer,
)
from app.services.product_utils import (
    ProductIntent,
    detect_product_intent,
    is_multi_product_question,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

_CONVERSATIONAL_PATTERNS = {
    "hi": "Hello! I can help answer questions about the uploaded FAQ documents.",
    "hello": "Hello! I can help answer questions about the uploaded FAQ documents.",
    "hey": "Hello! I can help answer questions about the uploaded FAQ documents.",
    "how are you": "I'm doing well and ready to help with your questions.",
    "who are you": "I am a FAQ assistant that helps answer questions from the uploaded documentation.",
}


def get_conversational_reply(question: str) -> str | None:
    """Return a friendly reply for simple conversational prompts."""
    normalized = " ".join(question.lower().strip().split())
    if not normalized:
        return None

    if normalized in _CONVERSATIONAL_PATTERNS:
        return _CONVERSATIONAL_PATTERNS[normalized]

    if normalized.startswith("hi ") or normalized.startswith("hello ") or normalized.startswith("hey "):
        return _CONVERSATIONAL_PATTERNS["hi"]

    if normalized.startswith("how are you"):
        return _CONVERSATIONAL_PATTERNS["how are you"]

    if normalized in ("who are you", "who are you?"):
        return _CONVERSATIONAL_PATTERNS["who are you"]

    return None


def get_retriever(store: MemoryStore = Depends(get_memory_store)) -> Retriever:
    return MemoryRetriever(store)


def _negative_scope_response(question: str, intent: ProductIntent) -> str | None:
    """Return a direct answer for out-of-scope product questions."""
    q_lower = question.lower()
    if intent == ProductIntent.LABELSMART:
        if any(term in q_lower for term in ("batch manufacturing record", "batch manufacturing records", "bmr", "mbr")):
            return "No. LabelSmart is designed for pharmaceutical artwork and packaging verification. Batch Manufacturing Record review is handled by BatchSmart."
    if intent == ProductIntent.BATCHSMART:
        if any(term in q_lower for term in ("packaging artwork", "artwork", "label artwork")):
            return "No. Packaging artwork verification is performed by LabelSmart."
    return None


def _clarification_response() -> str:
    return "Are you referring to BatchSmart or LabelSmart?"


def _retrieval_params(intent: ProductIntent, question: str) -> tuple[str | None, bool, bool]:
    """Map product intent to search filter, multi-product allowance, and overview mode."""
    if intent == ProductIntent.COMPARE:
        return None, True, True
    if intent == ProductIntent.BATCHSMART:
        return "BatchSmart", False, False
    if intent == ProductIntent.LABELSMART:
        return "LabelSmart", False, False
    if is_multi_product_question(question):
        return None, True, True
    return None, False, False


def _unique_sources(sections) -> list[SourceSnippet]:
    """Return one source entry per supporting document filename."""
    seen: set[str] = set()
    sources: list[SourceSnippet] = []
    for s in sections:
        if s.filename in seen:
            continue
        seen.add(s.filename)
        sources.append(
            SourceSnippet(
                document_id=s.document_id,
                filename=f"• {s.filename}",
                section=s.section,
                score=round(s.score, 3),
            )
        )
    return sources


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    store: MemoryStore = Depends(get_memory_store),
    retriever: Retriever = Depends(get_retriever),
) -> ChatResponse:
    if store.is_empty():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No documents have been uploaded yet. Upload a document before chatting.",
        )

    conversational_reply = get_conversational_reply(request.question)
    if conversational_reply is not None:
        return ChatResponse(
            answer=conversational_reply,
            sources=[],
            found_context=False,
            suggested_questions=[],
        )

    intent = detect_product_intent(request.question)

    if intent == ProductIntent.UNKNOWN:
        return ChatResponse(
            answer=_clarification_response(),
            sources=[],
            found_context=False,
            suggested_questions=[],
        )

    direct_answer = _negative_scope_response(request.question, intent)
    if direct_answer is not None:
        return ChatResponse(
            answer=direct_answer,
            sources=[],
            found_context=False,
            suggested_questions=[],
        )

    product_filter, allow_multi_product, overview_mode = _retrieval_params(intent, request.question)

    # If the client requested direct LLM mode, retrieve the top sections just
    # like the normal pipeline but send them directly to the model. This makes
    # the model answer based on uploaded document context while still keeping
    # the UX a single-step LLM response.
    if getattr(request, "use_direct_llm", False):
        document_filenames = request.document_filenames or None
        sections = retriever.retrieve(
            request.question,
            top_k=request.top_k,
            product_filter=product_filter,
            document_filenames=document_filenames,
            allow_multi_product=allow_multi_product,
            overview_mode=overview_mode,
        )

        if not sections:
            return ChatResponse(
                answer=NO_ANSWER_MESSAGE,
                sources=[],
                found_context=False,
                suggested_questions=[],
            )

        system_prompt, user_prompt = build_messages(request.question, sections, intent)

        try:
            raw_answer = generate_answer(system_prompt, user_prompt)
            answer, suggested_questions = parse_answer_and_questions(raw_answer)
        except LLMConfigurationError as exc:
            logger.error("LLM configuration error: %s", exc)
            return ChatResponse(
                answer=(
                    "Server misconfiguration: GROQ_API_KEY is not set. "
                    "Set the `GROQ_API_KEY` environment variable in your Render service."
                ),
                sources=[],
                found_context=False,
                suggested_questions=[],
                used_direct_llm=True,
            )
        except LLMRequestTooLargeError as exc:
            logger.error("LLM request too large: %s", exc)
            return ChatResponse(
                answer=(
                    "Your question is too long or the retrieved document context is too large for the current model. "
                    "Try asking a shorter question or upload fewer documents."
                ),
                sources=[],
                found_context=False,
                suggested_questions=[],
                used_direct_llm=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM call failed during direct-llm chat")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The language model call failed.") from exc

        return ChatResponse(
            answer=answer,
            sources=_unique_sources(sections),
            found_context=True,
            suggested_questions=suggested_questions,
            used_direct_llm=True,
        )

    document_filenames = request.document_filenames or None
    sections = retriever.retrieve(
        request.question,
        top_k=request.top_k,
        product_filter=product_filter,
        document_filenames=document_filenames,
        allow_multi_product=allow_multi_product,
        overview_mode=overview_mode,
    )

    if not sections:
        # No retrieval results — attempt a graceful fallback to the LLM so
        # the assistant can help with typos or re-interpret the question.
        try:
            filenames = ", ".join(d.filename for d in store.all_documents())
            system_prompt = (
                "You are a helpful assistant. The user asked a question but the "
                "retrieval system returned no matching document sections (possibly due to typos).")
            system_prompt += (
                " Use the uploaded documents where possible. Available documents: "
                f"{filenames}.\n\nIf you can infer the user's intent despite misspellings, answer concisely."
            )
            user_prompt = request.question
            raw_answer = generate_answer(system_prompt, user_prompt)
            answer, suggested_questions = parse_answer_and_questions(raw_answer)
        except LLMConfigurationError as exc:
            logger.error("LLM configuration error during fallback: %s", exc)
            return ChatResponse(
                answer=(
                    "Server misconfiguration: GROQ_API_KEY is not set. "
                    "Set the `GROQ_API_KEY` environment variable in your Render service."
                ),
                sources=[],
                found_context=False,
                suggested_questions=[],
                used_direct_llm=True,
            )
        except LLMRequestTooLargeError as exc:
            logger.error("LLM request too large during fallback: %s", exc)
            return ChatResponse(
                answer=(
                    "Your question is too long for the current model. "
                    "Try asking a shorter question or use the retrieval mode."
                ),
                sources=[],
                found_context=False,
                suggested_questions=[],
                used_direct_llm=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM fallback failed during chat")
            return ChatResponse(
                answer=NO_ANSWER_MESSAGE,
                sources=[],
                found_context=False,
                suggested_questions=[],
                used_direct_llm=True,
            )

        return ChatResponse(
            answer=answer,
            sources=[],
            found_context=False,
            suggested_questions=suggested_questions,
            used_direct_llm=True,
        )

    system_prompt, user_prompt = build_messages(request.question, sections, intent)

    try:
        raw_answer = generate_answer(system_prompt, user_prompt)
        answer, suggested_questions = parse_answer_and_questions(raw_answer)
    except LLMConfigurationError as exc:
        # Friendly chat response so the UI shows a helpful hint instead of a 500 page.
        logger.error("LLM configuration error: %s", exc)
        return ChatResponse(
            answer=(
                "Server misconfiguration: GROQ_API_KEY is not set. "
                "Set the `GROQ_API_KEY` environment variable in your Render service."
            ),
            sources=[],
            found_context=False,
            suggested_questions=[],
        )
    except LLMRequestTooLargeError as exc:
        logger.error("LLM request too large: %s", exc)
        return ChatResponse(
            answer=(
                "Your question is too long or the retrieved document context is too large for the current model. "
                "Try asking a shorter question or upload fewer documents."
            ),
            sources=[],
            found_context=False,
            suggested_questions=[],
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed during chat")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The language model call failed.") from exc

    return ChatResponse(
        answer=answer,
        sources=_unique_sources(sections),
        found_context=True,
        suggested_questions=suggested_questions,
    )
