"""
assistant_service.py
────────────────────────────────────────────────────────────────────────────────
Physical AI Assistant — DSR-CRAG pipeline
EWC Compute Platform · backend/app/services/assistant_service.py

Architecture
────────────
DSR-CRAG = Dual-State Corrective Retrieval-Augmented Generation

  State 1 — Primary retrieval
    embed(query) → Atlas vector search → score chunks
    → if quality OK → proceed to generation

  State 2 — Corrective re-retrieval (triggered when State 1 quality is low)
    reformulate_query(query, low-quality chunks) → re-embed → second Atlas search
    → merge and re-rank results → proceed to generation

  Generation
    format_context(chunks) → query(NIM) → validate_response(answer)
    → build_provenance(answer, chunks) → return AssistantResponse

Corpus chunk document schema (MongoDB collection: ewc_engineering_corpus)
────────────────────────────────────────────────────────────────────────────────
{
  "_id":             ObjectId,
  "chunk_id":        str,           # UUID — stable identifier across re-indexes
  "source":          str,           # Full citation, e.g. "ASHRAE Handbook 2021, Ch.3"
  "title":           str,           # Document / section title
  "domain":          str,           # cfd | fem | thermal | electromagnetic |
                                    # eda | optical | materials | general
  "chunk_text":      str,           # Raw text of this chunk (~512 tokens)
  "embedding":       [float],       # 1024-dim nv-embedqa-e5-v5 vector
  "page_number":     int | None,
  "section":         str | None,    # Section heading within source document
  "confidence_tier": str,           # authoritative | reference | model_estimate
  "created_at":      datetime (UTC),
  "metadata":        dict           # Arbitrary extras: DOI, URL, standard number, etc.
}

Atlas vector search index:
  name       : ewc_engineering_corpus   (settings.VECTOR_SEARCH_INDEX)
  field      : embedding
  dimensions : 1024
  similarity : cosine
  type       : knnVector
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.prompts import (
    ACTIVE_PROMPT_VERSION,
    ACTIVE_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

CORPUS_COLLECTION = "ewc_engineering_corpus"
EMBEDDING_DIMENSIONS = 1024          # nv-embedqa-e5-v5 output dimension
TOP_K_PRIMARY = 8                    # Chunks retrieved in State 1
TOP_K_CORRECTIVE = 6                 # Additional chunks retrieved in State 2
RELEVANCE_THRESHOLD = 0.72           # Cosine similarity floor; below → State 2
MIN_QUALITY_CHUNKS = 3               # Min chunks above threshold to skip State 2
MAX_CONTEXT_CHARS = 6_000            # Hard cap on context sent to NIM

# NOTE: _REFORMULATION_PROMPT belongs in app.core.prompts alongside the system
# prompt. It is defined here for Phase 1 and should be migrated to prompts.py
# in the next prompt versioning PR (create REFORMULATION_PROMPT_V1 there).
_REFORMULATION_PROMPT = (
    "The following engineering query returned low-relevance retrieval results. "
    "Reformulate it as a more specific, terminology-rich query that will retrieve "
    "better corpus matches. Return only the reformulated query — no explanation.\n\n"
    "Original query: {query}\n"
    "Low-relevance snippets: {snippets}"
)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class CorpusChunk(BaseModel):
    """A single retrieved chunk from the engineering corpus."""
    chunk_id: str
    source: str
    title: str
    domain: str
    chunk_text: str
    page_number: int | None = None
    section: str | None = None
    confidence_tier: str = "reference"  # authoritative | reference | model_estimate
    similarity_score: float = 0.0       # Populated after vector search
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProvenanceTag(BaseModel):
    """Provenance record attached to a specific claim in the response."""
    claim_index: int            # Position of the claim in the response (0-based)
    source: str                 # e.g. "ASHRAE Handbook 2021, Chapter 3"
    confidence: str             # high | moderate | low | model_estimate
    chunk_id: str
    similarity_score: float


class AssistantRequest(BaseModel):
    """Incoming request to the assistant service."""
    query: str = Field(..., min_length=1, max_length=2000)
    project_id: str | None = None       # Optional project scope for future filtering
    domain_hint: str | None = None      # cfd | fem | thermal | electromagnetic |
                                        # eda | optical | materials | general
    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class AssistantResponse(BaseModel):
    """Full response returned by the assistant service."""
    conversation_id: str
    turn_id: str
    answer: str
    provenance: list[ProvenanceTag]
    retrieval_state: str            # primary | corrective | fallback
    chunks_used: int
    model: str
    prompt_version: str             # From app.core.prompts.ACTIVE_PROMPT_VERSION
    latency_ms: float
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class RetrievalResult(BaseModel):
    """Internal result from a single retrieval pass."""
    chunks: list[CorpusChunk]
    mean_similarity: float
    quality_pass: bool  # True if mean_similarity >= RELEVANCE_THRESHOLD
                        # AND at least MIN_QUALITY_CHUNKS chunks are above it


# ─────────────────────────────────────────────────────────────────────────────
# NIM client — module-level singleton, shared across requests
# ─────────────────────────────────────────────────────────────────────────────

_nim_client: AsyncOpenAI | None = None


def _get_nim_client() -> AsyncOpenAI:
    """Return (or lazily initialise) the NIM AsyncOpenAI-compatible client."""
    global _nim_client
    if _nim_client is None:
        _nim_client = AsyncOpenAI(
            base_url=settings.NIM_BASE_URL,
            api_key=settings.NIM_API_KEY,
            http_client=httpx.AsyncClient(timeout=60.0),
        )
    return _nim_client


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — embed()
# ─────────────────────────────────────────────────────────────────────────────

async def embed(text: str) -> list[float]:
    """
    Embed a text string using NVIDIA NIM nv-embedqa-e5-v5.

    Returns a 1024-dimensional float vector.
    The `input_type: "query"` parameter is required by NIM to distinguish
    query vectors from passage vectors at retrieval time.

    Raises:
        ValueError: if the returned embedding has unexpected dimensions.
        httpx.HTTPStatusError: on NIM API failure.
    """
    client = _get_nim_client()
    response = await client.embeddings.create(
        model=settings.NIM_EMBEDDING_MODEL,   # nvidia/nv-embedqa-e5-v5
        input=text,
        encoding_format="float",
        extra_body={"input_type": "query"},
    )
    vector: list[float] = response.data[0].embedding
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Unexpected embedding dimension: got {len(vector)}, "
            f"expected {EMBEDDING_DIMENSIONS}. "
            f"Check NIM_EMBEDDING_MODEL in settings."
        )
    return vector


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Vector search (Atlas)
# ─────────────────────────────────────────────────────────────────────────────

async def _vector_search(
    db: AsyncIOMotorDatabase,
    query_vector: list[float],
    top_k: int,
    domain_filter: str | None = None,
) -> list[CorpusChunk]:
    """
    Run a MongoDB Atlas $vectorSearch against the engineering corpus.

    Expected Atlas index configuration:
      index name : settings.VECTOR_SEARCH_INDEX  ("ewc_engineering_corpus")
      path       : embedding
      dimensions : 1024
      similarity : cosine
      type       : knnVector

    numCandidates is set to top_k × 10 to give Atlas enough candidates to
    satisfy the domain filter without reducing effective recall.
    """
    pipeline: list[dict[str, Any]] = [
        {
            "$vectorSearch": {
                "index": settings.VECTOR_SEARCH_INDEX,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": top_k * 10,
                "limit": top_k,
            }
        },
        {
            "$project": {
                "chunk_id": 1,
                "source": 1,
                "title": 1,
                "domain": 1,
                "chunk_text": 1,
                "page_number": 1,
                "section": 1,
                "confidence_tier": 1,
                "metadata": 1,
                "similarity_score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    if domain_filter:
        pipeline.append({"$match": {"domain": domain_filter}})

    chunks: list[CorpusChunk] = []
    async for doc in db[CORPUS_COLLECTION].aggregate(pipeline):
        doc.pop("_id", None)
        chunks.append(CorpusChunk(**doc))

    return chunks


def _score_retrieval(chunks: list[CorpusChunk]) -> RetrievalResult:
    """
    Evaluate the quality of a retrieval pass.

    Passes when:
      - Mean cosine similarity >= RELEVANCE_THRESHOLD (0.72), AND
      - At least MIN_QUALITY_CHUNKS (3) chunks individually exceed the threshold.
    Either condition failing triggers DSR State 2 corrective retrieval.
    """
    if not chunks:
        return RetrievalResult(chunks=[], mean_similarity=0.0, quality_pass=False)

    scores = [c.similarity_score for c in chunks]
    mean_sim = sum(scores) / len(scores)
    above_threshold = sum(1 for s in scores if s >= RELEVANCE_THRESHOLD)
    quality_pass = (
        mean_sim >= RELEVANCE_THRESHOLD
        and above_threshold >= MIN_QUALITY_CHUNKS
    )
    return RetrievalResult(
        chunks=chunks,
        mean_similarity=round(mean_sim, 4),
        quality_pass=quality_pass,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Corrective re-retrieval (DSR State 2)
# ─────────────────────────────────────────────────────────────────────────────

async def _reformulate_query(
    original_query: str,
    low_quality_chunks: list[CorpusChunk],
) -> str:
    """
    Use NIM to produce a more specific, corpus-aligned reformulation of a query
    that returned poor retrieval results in State 1.

    Uses temperature=0.3 (slightly higher than inference) to allow more
    diverse reformulation vocabulary while staying domain-appropriate.
    """
    client = _get_nim_client()
    snippets = " | ".join(c.chunk_text[:120] for c in low_quality_chunks[:3])
    prompt = _REFORMULATION_PROMPT.format(
        query=original_query,
        snippets=snippets,
    )
    response = await client.chat.completions.create(
        model=settings.NIM_MODEL_ENGINEERING,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=128,
    )
    reformulated: str = response.choices[0].message.content.strip()
    logger.info(
        "dsr_corrective_reformulation | original=%r reformulated=%r",
        original_query,
        reformulated,
    )
    return reformulated


async def _corrective_retrieve(
    db: AsyncIOMotorDatabase,
    original_query: str,
    state1_chunks: list[CorpusChunk],
    domain_hint: str | None,
) -> tuple[list[CorpusChunk], str]:
    """
    DSR State 2: reformulate → re-embed → re-search → merge with State 1.

    Merge strategy:
      - Keep top-3 State 1 chunks (best of a weak retrieval is still signal)
      - Append all State 2 chunks not already present (deduplicate by chunk_id)
      - Sort merged list by similarity_score descending

    Returns (merged_chunks, retrieval_state_label="corrective").
    """
    reformulated = await _reformulate_query(original_query, state1_chunks)
    corrective_vector = await embed(reformulated)
    corrective_chunks = await _vector_search(
        db, corrective_vector, TOP_K_CORRECTIVE, domain_hint
    )

    seen: set[str] = set()
    merged: list[CorpusChunk] = []

    for chunk in sorted(state1_chunks, key=lambda c: c.similarity_score, reverse=True)[:3]:
        if chunk.chunk_id not in seen:
            seen.add(chunk.chunk_id)
            merged.append(chunk)

    for chunk in corrective_chunks:
        if chunk.chunk_id not in seen:
            seen.add(chunk.chunk_id)
            merged.append(chunk)

    merged.sort(key=lambda c: c.similarity_score, reverse=True)
    return merged, "corrective"


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Format context
# ─────────────────────────────────────────────────────────────────────────────

def _format_context(chunks: list[CorpusChunk]) -> str:
    """
    Serialise retrieved chunks into a structured context block for NIM.

    Each chunk is labelled with its source and confidence_tier so the model
    can generate accurate provenance markers. Total character budget is capped
    at MAX_CONTEXT_CHARS to stay safely within the NIM context window.
    """
    parts: list[str] = []
    total_chars = 0

    for i, chunk in enumerate(chunks):
        header = (
            f"[CHUNK {i + 1}] "
            f"Source: {chunk.source} | "
            f"Domain: {chunk.domain} | "
            f"Confidence tier: {chunk.confidence_tier}"
        )
        if chunk.section:
            header += f" | Section: {chunk.section}"

        block = f"{header}\n{chunk.chunk_text}"

        if total_chars + len(block) > MAX_CONTEXT_CHARS:
            break

        parts.append(block)
        total_chars += len(block)

    return "\n\n---\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — query()
# ─────────────────────────────────────────────────────────────────────────────

async def query(prompt: str, context: str) -> str:
    """
    Send the engineer's query and formatted retrieval context to NIM.

    System prompt: ACTIVE_SYSTEM_PROMPT from app.core.prompts (versioned).
    Temperature:   settings.NIM_INFERENCE_TEMPERATURE (default 0.1) for
                   deterministic, reproducible engineering responses.
    """
    client = _get_nim_client()
    response = await client.chat.completions.create(
        model=settings.NIM_MODEL_ENGINEERING,
        messages=[
            {"role": "system", "content": ACTIVE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Retrieved context:\n\n{context}\n\n"
                    f"{'─' * 40}\n\n"
                    f"Engineer's query: {prompt}"
                ),
            },
        ],
        temperature=settings.NIM_INFERENCE_TEMPERATURE,
        max_tokens=1024,
    )
    return response.choices[0].message.content


# ─────────────────────────────────────────────────────────────────────────────
# Step 6 — Validate response
# ─────────────────────────────────────────────────────────────────────────────

_NUMERIC_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?(?:\s*[×x]\s*10[⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)?"
    r"(?:\s*(?:Pa|MPa|GPa|K|°C|W|kW|MW|J|kJ|m|mm|μm|nm|"
    r"kg|g|s|ms|Hz|kHz|MHz|GHz|rad|deg|N|kN|MN|"
    r"A|V|Ω|T|F|H|mol|cd|lm|lx|Wb|S|m²|m³|m/s|m/s²|"
    r"eV|dB|dBm|psi|bar|atm))?"
    r"\b"
)


def _validate_response(answer: str) -> list[str]:
    """
    Scan the NIM answer for numeric claims lacking provenance markers.

    Recognises the two canonical markers defined in ACTIVE_SYSTEM_PROMPT_V1:
      - "[Retrieved from: ..."
      - "[Model estimate, confidence: moderate — verify before use]"

    A number is considered tagged if either marker appears within 200 chars
    of it. Untagged values are logged as warnings — they do NOT block delivery.

    Returns a deduplicated list of untagged numeric strings.
    """
    numbers_found = _NUMERIC_PATTERN.findall(answer)
    untagged: list[str] = []

    for number in numbers_found:
        idx = answer.find(number)
        window = answer[max(0, idx - 200): idx + 200].lower()
        if "retrieved from" not in window and "model estimate" not in window:
            untagged.append(number)

    return list(set(untagged))


# ─────────────────────────────────────────────────────────────────────────────
# Step 7 — Build provenance
# ─────────────────────────────────────────────────────────────────────────────

def _tier_to_confidence(tier: str, similarity: float) -> str:
    """Map confidence_tier + similarity score to a human-readable label."""
    if tier == "authoritative" and similarity >= 0.85:
        return "high"
    if tier == "authoritative" and similarity >= RELEVANCE_THRESHOLD:
        return "moderate"
    if tier == "reference" and similarity >= 0.80:
        return "moderate"
    if tier == "model_estimate":
        return "model_estimate — verify before use"
    return "low"


def _build_provenance(
    answer: str,
    chunks: list[CorpusChunk],
) -> list[ProvenanceTag]:
    """
    Build a structured provenance list correlating source mentions in the
    answer text with their retrieved corpus chunks.

    Primary: look for explicit source name or chunk label in the answer.
    Fallback: tag top-3 chunks as implicit provenance so the caller always
    has a complete audit trail even when the model didn't surface source
    names directly in its text.
    """
    provenance: list[ProvenanceTag] = []
    claim_index = 0
    answer_lower = answer.lower()

    for i, chunk in enumerate(chunks):
        if (
            chunk.source.lower() in answer_lower
            or f"chunk {i + 1}" in answer_lower
        ):
            provenance.append(
                ProvenanceTag(
                    claim_index=claim_index,
                    source=chunk.source,
                    confidence=_tier_to_confidence(
                        chunk.confidence_tier, chunk.similarity_score
                    ),
                    chunk_id=chunk.chunk_id,
                    similarity_score=chunk.similarity_score,
                )
            )
            claim_index += 1

    # Fallback: ensure top-3 chunks are always in the audit trail
    if not provenance:
        for i, chunk in enumerate(chunks[:3]):
            provenance.append(
                ProvenanceTag(
                    claim_index=i,
                    source=chunk.source,
                    confidence=_tier_to_confidence(
                        chunk.confidence_tier, chunk.similarity_score
                    ),
                    chunk_id=chunk.chunk_id,
                    similarity_score=chunk.similarity_score,
                )
            )

    return provenance


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point — run_assistant()
# ─────────────────────────────────────────────────────────────────────────────

async def run_assistant(
    request: AssistantRequest,
    db: AsyncIOMotorDatabase,
) -> AssistantResponse:
    """
    Execute the full DSR-CRAG pipeline for a single assistant turn.

    Pipeline:
      1. embed(query)                      → query_vector
      2. State 1: _vector_search()         → state1_chunks
      3. _score_retrieval()                → quality gate
         pass  → use state1_chunks
         fail  → _corrective_retrieve()   → merged_chunks
      4. _format_context(chunks)           → context string
      5. query(prompt, context)            → raw_answer
      6. _validate_response(answer)        → untagged_numerics (warnings only)
      7. _build_provenance(answer, chunks) → provenance list
      8. Return AssistantResponse

    Args:
        request: AssistantRequest with query and optional project/domain scope.
        db:      AsyncIOMotorDatabase injected by FastAPI dependency.

    Returns:
        AssistantResponse with answer, provenance, and retrieval metadata.
    """
    t_start = time.perf_counter()

    logger.info(
        "assistant_pipeline_start | conversation=%s turn=%s query_len=%d",
        request.conversation_id,
        request.turn_id,
        len(request.query),
    )

    # ── 1. Embed ──────────────────────────────────────────────────────────────
    query_vector = await embed(request.query)

    # ── 2. State 1: primary retrieval ─────────────────────────────────────────
    state1_chunks = await _vector_search(
        db, query_vector, TOP_K_PRIMARY, request.domain_hint
    )
    state1_result = _score_retrieval(state1_chunks)

    logger.info(
        "state1_retrieval | chunks=%d mean_sim=%.4f quality_pass=%s",
        len(state1_chunks),
        state1_result.mean_similarity,
        state1_result.quality_pass,
    )

    # ── 3. Quality gate ───────────────────────────────────────────────────────
    retrieval_state: str
    final_chunks: list[CorpusChunk]

    if state1_result.quality_pass:
        final_chunks = state1_result.chunks
        retrieval_state = "primary"

    elif not state1_chunks:
        # Corpus empty or query completely out-of-domain — generation fallback
        final_chunks = []
        retrieval_state = "fallback"
        logger.warning(
            "empty_retrieval_fallback | conversation=%s",
            request.conversation_id,
        )

    else:
        # DSR State 2: corrective re-retrieval
        final_chunks, retrieval_state = await _corrective_retrieve(
            db, request.query, state1_chunks, request.domain_hint
        )
        logger.info(
            "state2_corrective_complete | merged_chunks=%d",
            len(final_chunks),
        )

    # ── 4. Format context ─────────────────────────────────────────────────────
    if final_chunks:
        context = _format_context(final_chunks)
    else:
        context = (
            "No relevant corpus chunks retrieved. "
            "Answer from model knowledge only. "
            "All numeric values must be tagged as "
            "'[Model estimate, confidence: moderate — verify before use]'."
        )

    # ── 5. Query NIM ──────────────────────────────────────────────────────────
    raw_answer = await query(request.query, context)

    # ── 6. Validate response ──────────────────────────────────────────────────
    untagged_numerics = _validate_response(raw_answer)
    if untagged_numerics:
        logger.warning(
            "untagged_numeric_claims | turn=%s count=%d values=%s",
            request.turn_id,
            len(untagged_numerics),
            untagged_numerics,
        )

    # ── 7. Build provenance ───────────────────────────────────────────────────
    provenance = _build_provenance(raw_answer, final_chunks)

    # ── 8. Assemble and return ────────────────────────────────────────────────
    latency_ms = (time.perf_counter() - t_start) * 1000

    logger.info(
        "assistant_pipeline_complete | turn=%s state=%s chunks=%d latency_ms=%.1f",
        request.turn_id,
        retrieval_state,
        len(final_chunks),
        latency_ms,
    )

    return AssistantResponse(
        conversation_id=request.conversation_id,
        turn_id=request.turn_id,
        answer=raw_answer,
        provenance=provenance,
        retrieval_state=retrieval_state,
        chunks_used=len(final_chunks),
        model=settings.NIM_MODEL_ENGINEERING,
        prompt_version=ACTIVE_PROMPT_VERSION,
        latency_ms=round(latency_ms, 1),
    )


