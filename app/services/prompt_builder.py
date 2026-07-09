"""
Prompt builder service.

Turns retrieved sections + the user's question into the strict,
context-only prompt sent to the LLM.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from app.services.product_utils import ProductIntent
from app.services.search import RetrievedSection

NO_ANSWER_MESSAGE = "I couldn't find this information in the available documentation."

_SYSTEM_PROMPT = """You are a professional pharmaceutical FAQ assistant.

Answer questions clearly and naturally using ONLY the reference information provided below.

Rules:
- Answer ONLY from the reference information supplied. Do not use outside knowledge.
- Focus strictly on what the user asked. Do not mention unrelated products.
- If the user asks about one product, describe only that product. Ignore any reference sections about other products.
- Only combine information from multiple products when the user explicitly asks for a comparison or lists all products.
- For comparison questions, present a compact structured comparison with headings such as Purpose, Users, Input, Output, Primary Function, and Use Cases.
- If the question is ambiguous and no product is specified, ask a clarification question instead of guessing.
- If the user asks whether a product supports something outside its documented purpose, answer directly and clearly using the product's documented scope.
- Never say "the provided context", "the uploaded documents", "according to the documents", or anything that reveals how you find information.
- Never explain which documents were searched or how retrieval works.
- Write as a knowledgeable support assistant speaking directly to the user.
- Be concise, accurate, and professional. Avoid repetition and unnecessary detail.
- If the reference information does not contain the answer, respond with exactly: "I couldn't find this information in the available documentation."
- After your answer, suggest 3 related follow-up questions that can be answered from the reference information."""


def _intent_instruction(intent: ProductIntent) -> str:
    if intent == ProductIntent.BATCHSMART:
        return "The user is asking about BatchSmart. Answer using BatchSmart information only. Do not mention LabelSmart."
    if intent == ProductIntent.LABELSMART:
        return "The user is asking about LabelSmart. Answer using LabelSmart information only. Do not mention BatchSmart."
    if intent == ProductIntent.COMPARE:
        return "The user wants a comparison. Describe both BatchSmart and LabelSmart in a compact, structured comparison with headings such as Purpose, Users, Input, Output, Primary Function, and Use Cases."
    if intent == ProductIntent.GENERAL:
        return "Answer from the reference information. If it covers multiple products and the question asks about all products, describe each one separately."
    if intent == ProductIntent.UNKNOWN:
        return "The user did not specify a product. Ask a brief clarification question such as 'Are you referring to BatchSmart or LabelSmart?' Do not guess."
    return ""


def build_context_block(sections: List[RetrievedSection]) -> str:
    """Render retrieved sections into a plain-text reference block."""
    if not sections:
        return ""
    blocks = []
    for s in sections:
        blocks.append(f"[{s.filename} — {s.section}]\n{s.text}")
    return "\n\n---\n\n".join(blocks)


def build_messages(
    question: str,
    sections: List[RetrievedSection],
    intent: ProductIntent = ProductIntent.GENERAL,
) -> tuple[str, str]:
    """Build the (system_prompt, user_prompt) pair to send to the LLM."""
    context = build_context_block(sections)
    focus = _intent_instruction(intent)

    user_prompt = f"""Reference information:
{context if context else "(none)"}

{focus}

Question: {question}

Format your response as:
Answer: [Your answer here]

Related Questions:
1. [First suggested question]
2. [Second suggested question]
3. [Third suggested question]"""

    return _SYSTEM_PROMPT, user_prompt


def parse_answer_and_questions(response: str) -> Tuple[str, List[str]]:
    """Parse the LLM response to extract the answer and suggested questions."""
    questions: List[str] = []
    answer = response.strip()

    related_pattern = r'(?:Related Questions?|Follow[- ]?up Questions?|Suggested Questions?):\s*\n((?:\d+\..*?\n?)+)'
    match = re.search(related_pattern, response, re.IGNORECASE | re.MULTILINE)

    if match:
        answer = response[: match.start()].strip()
        answer = re.sub(r"^Answer:\s*", "", answer, flags=re.IGNORECASE).strip()

        questions_text = match.group(1)
        question_lines = re.findall(
            r"\d+\.\s*(.+?)(?=\n\d+\.|\n*$)", questions_text, re.MULTILINE
        )
        questions = [q.strip() for q in question_lines if q.strip()]
    else:
        lines = response.split("\n")
        answer_lines: List[str] = []
        question_lines: List[str] = []
        in_questions = False

        for line in lines:
            if re.match(r"^\d+\.\s+.+\?", line.strip()):
                in_questions = True
                question_text = re.sub(r"^\d+\.\s+", "", line.strip())
                question_lines.append(question_text)
            elif not in_questions:
                answer_lines.append(line)

        if question_lines:
            answer = "\n".join(answer_lines).strip()
            answer = re.sub(r"^Answer:\s*", "", answer, flags=re.IGNORECASE).strip()
            questions = question_lines

    return answer, questions[:3]
