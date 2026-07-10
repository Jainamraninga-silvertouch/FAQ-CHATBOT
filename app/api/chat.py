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
import json
from fastapi.responses import StreamingResponse
import asyncio

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
            # Instruct the model to silently infer intent if the user's wording
            # contains typos — do NOT tell the user about spelling mistakes or
            # ask them to rephrase. Answer concisely using the available docs.
            system_prompt = (
                "You are a professional pharmaceutical FAQ assistant. "
                "Use the uploaded documents to answer the question. "
                "If the user's wording appears misspelled or ambiguous, silently "
                "infer the likely intent and answer based on the documents; do not "
                "mention typos or ask the user to rephrase. Be concise and accurate."
            )
            system_prompt += (
                "\n\nAvailable documents: " f"{filenames}."
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


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    store: MemoryStore = Depends(get_memory_store),
    retriever: Retriever = Depends(get_retriever),
):
    """Stream the LLM answer as NDJSON lines. Each line is a JSON object:
    - {"delta": "partial text"}
    - final: {"done": true, "sources": [...], "used_direct_llm": bool}
    """
    if store.is_empty():
        async def empty_gen():
            yield json.dumps({"done": True, "error": "No documents uploaded"}) + "\n"

        return StreamingResponse(
            empty_gen(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    conversational_reply = get_conversational_reply(request.question)
    if conversational_reply is not None:
        async def conv_gen():
            yield json.dumps({"delta": conversational_reply}) + "\n"
            yield json.dumps({"done": True, "sources": [], "used_direct_llm": False}) + "\n"

        return StreamingResponse(
            conv_gen(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    intent = detect_product_intent(request.question)
    if intent == ProductIntent.UNKNOWN:
        async def clar_gen():
            yield json.dumps({"delta": _clarification_response()}) + "\n"
            yield json.dumps({"done": True, "sources": [], "used_direct_llm": False}) + "\n"

        return StreamingResponse(
            clar_gen(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    direct_answer = _negative_scope_response(request.question, intent)
    if direct_answer is not None:
        async def neg_gen():
            yield json.dumps({"delta": direct_answer}) + "\n"
            yield json.dumps({"done": True, "sources": [], "used_direct_llm": False}) + "\n"

        return StreamingResponse(
            neg_gen(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    product_filter, allow_multi_product, overview_mode = _retrieval_params(intent, request.question)

    # For streaming, reuse the same logic as /chat but stream the resulting
    # answer in small chunks (NDJSON) so the client can render progressively.
    use_direct = getattr(request, "use_direct_llm", False)

    document_filenames = request.document_filenames or None
    sections = retriever.retrieve(
        request.question,
        top_k=request.top_k,
        product_filter=product_filter,
        document_filenames=document_filenames,
        allow_multi_product=allow_multi_product,
        overview_mode=overview_mode,
    )

    # If no sections found and not direct mode, fall back to LLM as earlier
    if not sections and not use_direct:
        # call LLM fallback (synchronous) and stream its result
        try:
            filenames = ", ".join(d.filename for d in store.all_documents())
            system_prompt = (
                "You are a professional pharmaceutical FAQ assistant. "
                "Use the uploaded documents to answer the question. "
                "If the user's wording appears misspelled or ambiguous, silently "
                "infer the likely intent and answer based on the documents; do not "
                "mention typos or ask the user to rephrase. Be concise and accurate."
            )
            system_prompt += ("\n\nAvailable documents: " f"{filenames}.")
            user_prompt = request.question
            raw_answer = generate_answer(system_prompt, user_prompt)
            answer, suggested_questions = parse_answer_and_questions(raw_answer)
            # stream the answer as NDJSON chunks
            async def fallback_gen():
                chunk_size = 120
                for i in range(0, len(answer), chunk_size):
                    yield json.dumps({"delta": answer[i : i + chunk_size]}) + "\n"
                yield json.dumps({"done": True, "sources": [], "used_direct_llm": True}) + "\n"

            return StreamingResponse(
                fallback_gen(),
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        except Exception:
            async def fail_gen():
                yield json.dumps({"done": True, "error": "LLM call failed"}) + "\n"

            return StreamingResponse(
                fail_gen(),
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    # Build messages and call LLM (either direct mode or retrieval-based)
    system_prompt, user_prompt = build_messages(request.question, sections, intent)

    try:
        raw_answer = generate_answer(system_prompt, user_prompt)
        answer, suggested_questions = parse_answer_and_questions(raw_answer)
    except Exception:
        async def err_gen():
            yield json.dumps({"done": True, "error": "LLM call failed"}) + "\n"

        return StreamingResponse(
            err_gen(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    sources = _unique_sources(sections) if sections else []
    used_direct_flag = bool(use_direct or not sections)

    async def gen():
        chunk_size = 120
        for i in range(0, len(answer), chunk_size):
            yield json.dumps({"delta": answer[i : i + chunk_size]}) + "\n"
        yield json.dumps({"done": True, "sources": [s.dict() for s in sources], "used_direct_llm": used_direct_flag}) + "\n"

    # Add a small debug log so we can trace streaming on the server side.
    logger.info("Starting streaming response for question: %s", request.question)
    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/stream-test")
async def stream_test():
    """Simple streaming test endpoint that yields fixed NDJSON chunks with a delay.
    Use this to verify browser streaming and client JS handling without calling the LLM.
    """
    async def gen():
        parts = [
            {"delta": "This is a streaming test. "},
            {"delta": "If you see this in the console, streaming works. "},
            {"delta": "Finalizing test output."},
        ]
        for p in parts:
            yield json.dumps(p) + "\n"
            await asyncio.sleep(0.08)
        yield json.dumps({"done": True, "sources": [], "used_direct_llm": False}) + "\n"

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
