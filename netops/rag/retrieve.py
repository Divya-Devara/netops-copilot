import re
from functools import lru_cache

DB_DIR = "netops/rag/chroma_db"
_TOKEN = re.compile(r"[A-Za-z0-9_\-\.]+")

def tokenize(text: str) -> list[str]:
    """Lowercase word tokens; strips punctuation so 'ExStart,' matches 'exstart'."""
    return [t.strip(".-") for t in _TOKEN.findall(text.lower()) if t.strip(".-")]

@lru_cache(maxsize=1)
def _index():
    """Load the embedding model, Chroma collection and BM25 index once, on first search."""
    import chromadb
    from chromadb.utils import embedding_functions
    from rank_bm25 import BM25Okapi

    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="BAAI/bge-small-en-v1.5")
    client = chromadb.PersistentClient(path=DB_DIR)
    collection = client.get_collection(name="netops_docs", embedding_function=emb_fn)
    data = collection.get(include=["documents", "metadatas"])
    bm25 = BM25Okapi([tokenize(d) for d in data["documents"]])
    return collection, bm25, data["ids"], data["metadatas"], data["documents"]

def reciprocal_rank_fusion(*ranked_lists, k: int = 5) -> list[dict]:
    """Each ranked list holds (id, meta, doc) tuples, best first."""
    scores: dict[str, dict] = {}
    for hits in ranked_lists:
        for rank, (doc_id, meta, doc) in enumerate(hits):
            entry = scores.setdefault(doc_id, {"score": 0.0, "meta": meta, "doc": doc})
            entry["score"] += 1 / (rank + 60)
    best = sorted(scores.items(), key=lambda kv: kv[1]["score"], reverse=True)[:k]
    return [{"id": i, "meta": v["meta"], "doc": v["doc"], "score": v["score"]} for i, v in best]

def search(query: str, k: int = 5) -> list[dict]:
    """Hybrid (vector + BM25) search. Returns structured hits: id, meta, doc, score."""
    collection, bm25, ids, metas, docs = _index()
    resp = collection.query(query_texts=[query], n_results=k * 2)
    vector_hits = list(zip(resp["ids"][0], resp["metadatas"][0], resp["documents"][0]))
    scores = bm25.get_scores(tokenize(query))
    top = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:k * 2]
    bm25_hits = [(ids[i], metas[i], docs[i]) for i in top if scores[i] > 0]
    return reciprocal_rank_fusion(vector_hits, bm25_hits, k=k)

def format_hits(hits: list[dict]) -> str:
    return "\n".join(f"--- SOURCE ID: {h['id']} ---\n{h['doc']}\n" for h in hits)

def search_docs(query: str, k: int = 5) -> str:
    """Backward-compatible string form used in prompts."""
    return format_hits(search(query, k))

if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "How do I configure an OSPF passive interface?"
    print(f"\n--- Searching for: '{query}' ---\n")
    print(search_docs(query))
