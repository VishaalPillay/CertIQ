# integrations/foundry_iq.py
from functools import lru_cache
import logging
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from agents.config import settings

logger = logging.getLogger(__name__)

class FoundryIQ:
    """
    Centralised grounded retrieval service backed by Azure AI Search.
    Uses hybrid search: semantic ranking over BM25 keyword results.
    Returns chunks ready for direct injection into agent system prompts.
    """

    def __init__(self):
        self._client = SearchClient(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_index_name,
            credential=AzureKeyCredential(settings.azure_search_admin_key),
        )

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """
        Hybrid search: semantic re-ranking over BM25.
        Returns list of dicts with keys:
          - content: str          (the chunk text — inject verbatim into prompt)
          - source_file: str      (e.g. "az204_study_guide.md")
          - section_heading: str  (e.g. "Azure Functions Triggers")
          - chunk_id: str         (unique identifier for citation tracking)
          - score: float          (relevance score from search engine)
        """
        try:
            results = self._client.search(
                search_text=query,
                query_type="semantic",
                semantic_configuration_name="certiq-semantic",
                top=top_k,
                select=["content", "source_file", "section_heading", "chunk_id"],
            )

            chunks = []
            for result in results:
                chunks.append({
                    "content": result.get("content", ""),
                    "source_file": result.get("source_file", ""),
                    "section_heading": result.get("section_heading", ""),
                    "chunk_id": result.get("chunk_id", ""),
                    "score": result.get("@search.score", 0.0),
                })
            return chunks
        except Exception as e:
            logger.error("Azure AI Search hybrid query failed: %s", e)
            return []

    def search_with_filter(self, query: str, source_file: str, top_k: int = 3) -> list[dict[str, Any]]:
        """
        Search within a specific source document only.
        Used when an agent needs to restrict retrieval to one guide (e.g. az204 only).
        Uses OData filter: $filter=source_file eq '{source_file}'
        """
        try:
            results = self._client.search(
                search_text=query,
                query_type="semantic",
                semantic_configuration_name="certiq-semantic",
                filter=f"source_file eq '{source_file}'",
                top=top_k,
                select=["content", "source_file", "section_heading", "chunk_id"],
            )

            chunks = []
            for result in results:
                chunks.append({
                    "content": result.get("content", ""),
                    "source_file": result.get("source_file", ""),
                    "section_heading": result.get("section_heading", ""),
                    "chunk_id": result.get("chunk_id", ""),
                    "score": result.get("@search.score", 0.0),
                })
            return chunks
        except Exception as e:
            logger.error("Azure AI Search filtered query failed for %s: %s", source_file, e)
            return []

@lru_cache(maxsize=1)
def get_foundry_iq() -> FoundryIQ:
    """Singleton accessor. Import this function, not the class directly."""
    return FoundryIQ()
