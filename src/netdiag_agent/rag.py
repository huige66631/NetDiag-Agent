from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from netdiag_agent.models import NetworkSnapshot


KNOWLEDGE_DIR = Path("docs/knowledge")
CHROMA_DIR = Path("data/chroma")
COLLECTION_NAME = "netdiag_knowledge"


@dataclass(frozen=True)
class RagHit:
    title: str
    source: str
    content: str
    distance: float | None = None


class HashingEmbeddingFunction:
    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def name(self) -> str:
        return "netdiag-hashing-embedding"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [hashing_embedding(text, self.dimensions) for text in input]

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)


def hashing_embedding(text: str, dimensions: int = 384) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    latin = re.findall(r"[a-z0-9_.-]{2,}", lowered)
    chinese = [
        lowered[index : index + 2]
        for index in range(max(0, len(lowered) - 1))
        if "\u4e00" <= lowered[index] <= "\u9fff"
    ]
    return latin + chinese


def get_collection():
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=HashingEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )


def iter_knowledge_chunks(knowledge_dir: Path = KNOWLEDGE_DIR) -> Iterable[tuple[str, str, str]]:
    for path in sorted(knowledge_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = path.stem.replace("-", " ")
        chunks = [chunk.strip() for chunk in re.split(r"\n(?=## )", text) if chunk.strip()]
        for index, chunk in enumerate(chunks):
            first_line = chunk.splitlines()[0].strip("# ").strip()
            chunk_title = first_line or title
            yield f"{path.name}:{index}", chunk_title, chunk


def build_knowledge_base(force: bool = False) -> int:
    collection = get_collection()
    if force:
        existing = collection.get()
        ids = existing.get("ids") or []
        if ids:
            collection.delete(ids=ids)

    existing_ids = set(collection.get().get("ids") or [])
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []
    for doc_id, title, chunk in iter_knowledge_chunks():
        if doc_id in existing_ids:
            continue
        ids.append(doc_id)
        documents.append(chunk)
        metadatas.append({"title": title, "source": doc_id.split(":")[0]})

    if ids:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
    return collection.count()


def retrieve_knowledge(
    user_context: str,
    snapshot: NetworkSnapshot | None = None,
    top_k: int = 4,
) -> list[RagHit]:
    build_knowledge_base(force=False)
    collection = get_collection()
    query = build_retrieval_query(user_context, snapshot)
    result = collection.query(query_texts=[query], n_results=top_k)

    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0] if result.get("distances") else []

    hits: list[RagHit] = []
    for index, document in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else None
        hits.append(
            RagHit(
                title=str(metadata.get("title") or "网络诊断知识"),
                source=str(metadata.get("source") or "knowledge"),
                content=document,
                distance=distance,
            )
        )
    return hits


def build_retrieval_query(user_context: str, snapshot: NetworkSnapshot | None = None) -> str:
    parts = [user_context or "通用网络故障诊断"]
    if snapshot and snapshot.diagnosis:
        parts.append(snapshot.diagnosis.summary)
        parts.extend(snapshot.diagnosis.evidence[:4])
    return "\n".join(parts)


def rag_hits_to_context(hits: list[RagHit]) -> str:
    if not hits:
        return "未检索到相关网络知识。"
    lines: list[str] = []
    for index, hit in enumerate(hits, start=1):
        lines.append(f"[RAG 知识 {index}] {hit.title}（来源：{hit.source}）")
        lines.append(hit.content[:1200])
    return "\n\n".join(lines)


def rag_hits_to_rows(hits: list[RagHit]) -> list[dict[str, object]]:
    return [
        {
            "标题": hit.title,
            "来源": hit.source,
            "距离": None if hit.distance is None else round(float(hit.distance), 4),
            "片段": hit.content[:160].replace("\n", " "),
        }
        for hit in hits
    ]
