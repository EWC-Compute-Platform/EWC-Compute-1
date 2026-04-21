"""
seed_corpus.py
────────────────────────────────────────────────────────────────────────────────
Physical AI Assistant — Engineering corpus seeding script
EWC Compute Platform · scripts/seed_corpus.py

Purpose
───────
Populates the MongoDB Atlas collection `ewc_engineering_corpus` with
embedded, chunked engineering documents that the Physical AI Assistant
retrieves via vector search.

Each document is split into overlapping chunks, embedded via NVIDIA NIM
(nv-embedqa-e5-v5, 1024-dim), and inserted as a corpus chunk document
following the schema defined in assistant_service.py.

Atlas tier note
───────────────
Embedding and insertion work on any MongoDB tier including M0 free tier.
The Atlas $vectorSearch stage used at query time requires M10 or above.
Use --dry-run to test the full embedding pipeline without writing to Atlas.
The script is production-ready — no changes needed when upgrading the cluster.

Usage
─────
  # Seed from the built-in Phase 1 source list (no arguments needed)
  python scripts/seed_corpus.py

  # Seed a single Markdown or PDF file
  python scripts/seed_corpus.py --source path/to/document.md

  # Seed a directory of files
  python scripts/seed_corpus.py --source path/to/docs/

  # Test embedding pipeline without writing to Atlas
  python scripts/seed_corpus.py --dry-run

  # Re-embed and replace existing chunks for a specific source
  python scripts/seed_corpus.py --source doc.md --replace

  # Show what would be inserted without embedding (fast check)
  python scripts/seed_corpus.py --list-sources

Environment variables required
───────────────────────────────
  MONGODB_URI         MongoDB connection string
  MONGODB_DB_NAME     Database name (default: ewc_compute_dev)
  NIM_API_KEY         NVIDIA NIM API key
  NIM_EMBEDDING_MODEL Embedding model name (default: nvidia/nv-embedqa-e5-v5)
  NIM_BASE_URL        NIM base URL (default: https://integrate.api.nvidia.com/v1)

Corpus chunk schema (mirrors assistant_service.py)
───────────────────────────────────────────────────
{
  "chunk_id":        str    UUID, stable across re-ingestion
  "source":          str    Full citation string
  "title":           str    Document / section title
  "domain":          str    cfd|fem|thermal|electromagnetic|eda|optical|
                            materials|general
  "chunk_text":      str    ~512 token chunk of source text
  "embedding":       list   1024-dim float vector (nv-embedqa-e5-v5)
  "page_number":     int?   Page number if applicable
  "section":         str?   Section heading within source
  "confidence_tier": str    authoritative|reference|model_estimate
  "created_at":      str    ISO 8601 UTC
  "metadata":        dict   DOI, URL, standard number, etc.
}
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# ── Conditional imports — graceful degradation for local dev ──────────────────
try:
    import motor.motor_asyncio as motor
    MOTOR_AVAILABLE = True
except ImportError:
    MOTOR_AVAILABLE = False
    print("[warning] motor not installed — dry-run mode only")

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("[warning] openai package not installed — dry-run mode only")

# ── Settings (read directly from env — script runs outside FastAPI context) ───
MONGODB_URI         = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME     = os.environ.get("MONGODB_DB_NAME", "ewc_compute_dev")
NIM_BASE_URL        = os.environ.get("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NIM_API_KEY         = os.environ.get("NIM_API_KEY", "")
NIM_EMBEDDING_MODEL = os.environ.get("NIM_EMBEDDING_MODEL", "nvidia/nv-embedqa-e5-v5")

CORPUS_COLLECTION   = "ewc_engineering_corpus"
EMBEDDING_DIM       = 1024
CHUNK_SIZE_TOKENS   = 512    # target tokens per chunk
CHUNK_OVERLAP_CHARS = 200    # character overlap between adjacent chunks
BATCH_SIZE          = 8      # embeddings per NIM call (stay within rate limits)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_corpus")


# ─────────────────────────────────────────────────────────────────────────────
# Corpus chunk dataclass (plain dict — no FastAPI dependency here)
# ─────────────────────────────────────────────────────────────────────────────

def make_chunk(
    text: str,
    source: str,
    title: str,
    domain: str,
    confidence_tier: str = "reference",
    section: str | None = None,
    page_number: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build a corpus chunk document ready for Atlas insertion.
    embedding is set to [] here and filled in by embed_chunks().

    chunk_id is derived from a hash of (source + text) so that
    re-ingesting the same content produces the same ID — enabling
    idempotent upserts and stable references in provenance tags.
    """
    content_hash = hashlib.sha256(f"{source}::{text}".encode()).hexdigest()[:16]
    return {
        "chunk_id": f"chunk_{content_hash}",
        "source": source,
        "title": title,
        "domain": domain,
        "chunk_text": text,
        "embedding": [],                     # filled by embed_chunks()
        "page_number": page_number,
        "section": section,
        "confidence_tier": confidence_tier,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Text splitting
# ─────────────────────────────────────────────────────────────────────────────

def split_text(
    text: str,
    chunk_size_chars: int = CHUNK_SIZE_TOKENS * 4,  # ~4 chars per token
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
) -> list[str]:
    """
    Split text into overlapping chunks.

    Strategy: split on paragraph boundaries first (double newline),
    then re-merge paragraphs into target-size chunks with overlap.
    This preserves semantic units better than fixed-character slicing.

    overlap_chars ensures that sentences spanning a chunk boundary
    appear in both chunks, preventing retrieval misses on queries
    that match the boundary region.
    """
    # Normalise whitespace
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    paragraphs = text.split("\n\n")

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding this paragraph stays within budget, append it
        if len(current) + len(para) < chunk_size_chars:
            current = current + "\n\n" + para if current else para
        else:
            # Save current chunk
            if current:
                chunks.append(current.strip())
            # Start new chunk with overlap from previous
            overlap_text = current[-overlap_chars:] if current else ""
            current = overlap_text + "\n\n" + para if overlap_text else para

    if current.strip():
        chunks.append(current.strip())

    # Safety filter: drop chunks that are too short to be useful
    return [c for c in chunks if len(c) > 100]


def extract_sections(text: str) -> list[tuple[str, str]]:
    """
    Extract (section_heading, section_text) pairs from Markdown.
    Used to set the `section` field on corpus chunks.
    Falls back to a single section with empty heading if no headings found.
    """
    heading_pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    matches = list(heading_pattern.finditer(text))

    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if section_text:
            sections.append((heading, section_text))

    return sections


# ─────────────────────────────────────────────────────────────────────────────
# Embedding
# ─────────────────────────────────────────────────────────────────────────────

async def embed_chunks(
    chunks: list[dict[str, Any]],
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """
    Embed all chunks in batches using NVIDIA NIM nv-embedqa-e5-v5.

    Each chunk's `embedding` field is populated in-place.
    In dry-run mode, a zero vector is substituted so the rest of the
    pipeline can be validated without a NIM API key.

    NIM uses `input_type: "passage"` for corpus documents — distinct
    from `input_type: "query"` used in assistant_service.embed().
    This asymmetry is by design: the model is trained to maximise
    dot-product similarity between query vectors and passage vectors.
    """
    if dry_run:
        logger.info("dry-run | substituting zero vectors for %d chunks", len(chunks))
        for chunk in chunks:
            chunk["embedding"] = [0.0] * EMBEDDING_DIM
        return chunks

    if not OPENAI_AVAILABLE or not NIM_API_KEY:
        logger.error(
            "Cannot embed: openai package not installed or NIM_API_KEY not set. "
            "Use --dry-run to test without embedding."
        )
        sys.exit(1)

    client = AsyncOpenAI(
        base_url=NIM_BASE_URL,
        api_key=NIM_API_KEY,
        http_client=httpx.AsyncClient(timeout=60.0),
    )

    total = len(chunks)
    embedded = 0

    for i in range(0, total, BATCH_SIZE):
        batch = chunks[i: i + BATCH_SIZE]
        texts = [c["chunk_text"] for c in batch]

        try:
            response = await client.embeddings.create(
                model=NIM_EMBEDDING_MODEL,
                input=texts,
                encoding_format="float",
                extra_body={"input_type": "passage"},   # corpus documents
            )
        except Exception as exc:
            logger.error("embedding_failed | batch=%d error=%s", i // BATCH_SIZE, exc)
            raise

        for j, item in enumerate(response.data):
            vector = item.embedding
            if len(vector) != EMBEDDING_DIM:
                raise ValueError(
                    f"Unexpected embedding dim: {len(vector)} (expected {EMBEDDING_DIM})"
                )
            batch[j]["embedding"] = vector

        embedded += len(batch)
        logger.info("embedded %d / %d chunks", embedded, total)

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Atlas insertion
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_chunks(
    chunks: list[dict[str, Any]],
    dry_run: bool = False,
    replace: bool = False,
) -> dict[str, int]:
    """
    Upsert corpus chunks into MongoDB Atlas.

    Upsert strategy: match on `chunk_id` (content-hash based).
    - New chunks: inserted
    - Existing chunks with same content: skipped (idempotent)
    - Existing chunks with --replace flag: overwritten with new embedding

    Returns counts: {"inserted": n, "updated": n, "skipped": n}
    """
    if dry_run:
        logger.info("dry-run | would upsert %d chunks (skipping Atlas write)", len(chunks))
        return {"inserted": len(chunks), "updated": 0, "skipped": 0}

    if not MOTOR_AVAILABLE:
        logger.error("motor not installed — cannot write to Atlas")
        sys.exit(1)

    client = motor.AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_DB_NAME]
    collection = db[CORPUS_COLLECTION]

    counts = {"inserted": 0, "updated": 0, "skipped": 0}

    for chunk in chunks:
        existing = await collection.find_one({"chunk_id": chunk["chunk_id"]})

        if existing and not replace:
            counts["skipped"] += 1
            continue

        result = await collection.replace_one(
            {"chunk_id": chunk["chunk_id"]},
            chunk,
            upsert=True,
        )

        if result.upserted_id:
            counts["inserted"] += 1
        else:
            counts["updated"] += 1

    client.close()
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# Source definitions — Phase 1 initial corpus
# ─────────────────────────────────────────────────────────────────────────────

def get_phase1_sources() -> list[dict[str, Any]]:
    """
    Returns the Phase 1 initial corpus source list.

    Each entry defines how to locate, classify, and chunk one source.
    Sources without a `path` are placeholders — they log a warning and
    are skipped until the referenced file exists locally.

    The corpus is intentionally small and high-quality in Phase 1.
    Each source is manually reviewed before being added here.

    confidence_tier values:
      authoritative — peer-reviewed, standards body, or official NVIDIA docs
      reference     — high-quality technical reference (EWC Substack, curated)
      model_estimate — not used for seeding (only for live assistant responses)
    """
    repo_root = Path(__file__).parent.parent
    substack_dir = repo_root / "Substack-Articles"

    return [
        # ── EWC Substack back-catalogue ──────────────────────────────────────
        {
            "path": substack_dir / "EWC_Compute_Project_Kickoff.md",
            "source": "EWC Compute Kickoff — Engineering World Company, 2026",
            "title": "EWC Compute Architecture and Build Plan",
            "domain": "general",
            "confidence_tier": "reference",
            "metadata": {
                "url": "https://engineeringworldcompany.substack.com/p/ewc-compute-kickoff"
            },
        },
        {
            "path": substack_dir / "EWC_Compute_Substack_Flow360_Post.md",
            "source": "EWC Compute — Flow360 Integration, Engineering World Company, 2026",
            "title": "Flow360 GPU-Native CFD Integration",
            "domain": "cfd",
            "confidence_tier": "reference",
            "metadata": {
                "url": "https://engineeringworldcompany.substack.com/p/ewc-compute-adds-flow360"
            },
        },
        {
            "path": substack_dir / "EWC_Compute_Substack_Post5_AIAssistant.md",
            "source": "EWC Compute — Physical AI Assistant Architecture, Engineering World Company, 2026",
            "title": "The AI Assistant That Does Not Hallucinate Physics",
            "domain": "general",
            "confidence_tier": "reference",
            "metadata": {
                "url": "https://engineeringworldcompany.substack.com/p/the-ai-assistant"
            },
        },
        {
            "path": substack_dir / "EWC_Compute_Substack_Polymathic_Overtone.md",
            "source": "EWC Compute — Polymathic AI Walrus and Overtone, Engineering World Company, 2026",
            "title": "Physics Foundation Model Layer: Walrus and Overtone",
            "domain": "general",
            "confidence_tier": "reference",
            "metadata": {
                "url": "https://engineeringworldcompany.substack.com/p/polymathic-overtone"
            },
        },
        # ── NVIDIA CAE reference (add when downloaded from NVIDIA docs) ───────
        # {
        #     "path": repo_root / "docs" / "nvidia" / "cae_canonical_workflow.md",
        #     "source": "NVIDIA Computer-Aided Engineering Documentation, 2025",
        #     "title": "NVIDIA CAE Canonical Workflow",
        #     "domain": "general",
        #     "confidence_tier": "authoritative",
        #     "metadata": {"url": "https://developer.nvidia.com/cae"},
        # },
        # ── Flow360 solver documentation (add when downloaded) ────────────────
        # {
        #     "path": repo_root / "docs" / "flexcompute" / "flow360_docs.md",
        #     "source": "Flow360 Documentation — Flexcompute, 2025",
        #     "title": "Flow360 Solver Reference",
        #     "domain": "cfd",
        #     "confidence_tier": "authoritative",
        #     "metadata": {"url": "https://docs.flexcompute.com/projects/flow360"},
        # },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# File ingestion
# ─────────────────────────────────────────────────────────────────────────────

def ingest_markdown_file(
    path: Path,
    source: str,
    title: str,
    domain: str,
    confidence_tier: str = "reference",
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Read a Markdown file, extract section structure, split into
    overlapping chunks, and return a list of corpus chunk dicts
    ready for embedding.
    """
    text = path.read_text(encoding="utf-8")
    sections = extract_sections(text)
    chunks: list[dict[str, Any]] = []

    for section_heading, section_text in sections:
        for chunk_text in split_text(section_text):
            chunks.append(
                make_chunk(
                    text=chunk_text,
                    source=source,
                    title=title,
                    domain=domain,
                    confidence_tier=confidence_tier,
                    section=section_heading or None,
                    metadata=metadata or {},
                )
            )

    return chunks


def ingest_source(source_def: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Ingest a single source definition. Handles Markdown files.
    PDF support is added in Phase 2 (requires pdf-reading skill).
    """
    path = Path(source_def["path"])
    if not path.exists():
        logger.warning("source_not_found | path=%s — skipping", path)
        return []

    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        chunks = ingest_markdown_file(
            path=path,
            source=source_def["source"],
            title=source_def["title"],
            domain=source_def["domain"],
            confidence_tier=source_def.get("confidence_tier", "reference"),
            metadata=source_def.get("metadata", {}),
        )
        logger.info(
            "ingested | file=%s chunks=%d domain=%s",
            path.name, len(chunks), source_def["domain"],
        )
        return chunks
    else:
        logger.warning("unsupported_file_type | path=%s — skipping", path)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:

    if args.list_sources:
        sources = get_phase1_sources()
        print(f"\nPhase 1 corpus sources ({len(sources)} total):\n")
        for s in sources:
            path = Path(s["path"])
            exists = "✓" if path.exists() else "✗ (not found)"
            print(f"  {exists}  [{s['domain']:14s}]  {s['title']}")
            print(f"           {path}")
        return

    # ── Collect source definitions ─────────────────────────────────────────
    if args.source:
        source_path = Path(args.source)
        if source_path.is_dir():
            source_defs = [
                {
                    "path": f,
                    "source": f.stem,
                    "title": f.stem.replace("_", " ").replace("-", " ").title(),
                    "domain": "general",
                    "confidence_tier": "reference",
                    "metadata": {},
                }
                for f in source_path.glob("**/*.md")
            ]
        else:
            source_defs = [{
                "path": source_path,
                "source": source_path.stem,
                "title": source_path.stem.replace("_", " ").title(),
                "domain": args.domain or "general",
                "confidence_tier": "reference",
                "metadata": {},
            }]
    else:
        source_defs = get_phase1_sources()

    # ── Ingest all sources into chunks ────────────────────────────────────
    all_chunks: list[dict[str, Any]] = []
    for source_def in source_defs:
        all_chunks.extend(ingest_source(source_def))

    if not all_chunks:
        logger.warning("no chunks produced — check source paths")
        return

    logger.info("total chunks to embed: %d", len(all_chunks))

    # ── Embed ──────────────────────────────────────────────────────────────
    all_chunks = await embed_chunks(all_chunks, dry_run=args.dry_run)

    # ── Insert into Atlas ──────────────────────────────────────────────────
    counts = await upsert_chunks(
        all_chunks,
        dry_run=args.dry_run,
        replace=args.replace,
    )

    # ── Report ─────────────────────────────────────────────────────────────
    print(
        f"\n{'DRY RUN — ' if args.dry_run else ''}"
        f"Corpus seeding complete\n"
        f"  Inserted : {counts['inserted']}\n"
        f"  Updated  : {counts['updated']}\n"
        f"  Skipped  : {counts['skipped']}\n"
        f"  Total    : {len(all_chunks)}\n"
    )

    if args.dry_run:
        print(
            "Atlas write skipped (--dry-run). "
            "Remove the flag to write to MongoDB Atlas.\n"
            "Note: $vectorSearch requires Atlas M10 or above.\n"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed the EWC Compute Physical AI Assistant corpus"
    )
    parser.add_argument(
        "--source",
        help="Path to a single file or directory to ingest. "
             "Defaults to the Phase 1 built-in source list.",
    )
    parser.add_argument(
        "--domain",
        default="general",
        choices=["cfd", "fem", "thermal", "electromagnetic",
                 "eda", "optical", "materials", "general"],
        help="Domain for --source file (ignored when using built-in sources)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline (chunking, embedding) without writing to Atlas",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Re-embed and overwrite existing chunks with the same chunk_id",
    )
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="Print the built-in Phase 1 source list and exit",
    )
    args = parser.parse_args()

    asyncio.run(main(args))

