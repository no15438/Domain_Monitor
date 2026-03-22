import chromadb
import os
from config import settings

_collection = None


def get_collection():
    global _collection
    if _collection is None:
        os.makedirs(settings.chroma_persist_dir, exist_ok=True)
        client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        _collection = client.get_or_create_collection(
            name="articles", metadata={"hnsw:space": "cosine"}
        )
    return _collection


def add_article(article_id: str, text: str, metadata: dict):
    col = get_collection()
    col.upsert(ids=[article_id], documents=[text], metadatas=[metadata])


def delete_document(doc_id: str):
    col = get_collection()
    col.delete(ids=[doc_id])


def search_articles(query: str, n_results: int = 5, where_filter: dict | None = None) -> list[dict]:
    col = get_collection()
    total = col.count()
    if total == 0:
        return []
    kwargs: dict = {"query_texts": [query], "n_results": min(n_results, total)}
    if where_filter:
        kwargs["where"] = where_filter
    results = col.query(**kwargs)
    articles = []
    for i in range(len(results["ids"][0])):
        articles.append(
            {
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0,
            }
        )
    return articles
