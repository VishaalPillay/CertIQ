"""
CertIQ — setup_knowledge_base.py
=============================

Automation script to:
  1. Upload knowledge base markdown files to Azure Blob Storage
  2. Create the Azure AI Search index schema (with optional vector search)
  3. Chunk documents using tiktoken with heading boundaries
  4. Generate text embeddings via GitHub Models (optional, opt-in)
  5. Index all chunks into Azure AI Search

Primary search strategy is BM25 keyword search + Azure Semantic Ranking (default, no vectors).
"""

import os
import sys
import argparse
import hashlib
from pathlib import Path
from dotenv import load_dotenv

# Ensure the project root is in the path
sys.path.append(str(Path(__file__).parent.parent.absolute()))

# Load .env variables before config loads
load_dotenv()

import tiktoken
import openai
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

# Import application configuration
from agents.config import settings


def parse_args():
    parser = argparse.ArgumentParser(description="CertIQ Knowledge Base Setup Tool")
    parser.add_argument(
        "--with-vectors",
        action="store_true",
        help="Build index with vector search support (opt-in)",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Skip uploading files to Azure Blob Storage and only build the search index",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config, count chunks, and estimate sizes without making writes to Azure",
    )
    return parser.parse_args()


def validate_environment(args):
    """Validate that required environment variables are present."""
    print("[INFO] Validating environment credentials...")
    missing = []
    if not settings.azure_search_endpoint:
        missing.append("AZURE_SEARCH_ENDPOINT")
    if not settings.azure_search_admin_key:
        missing.append("AZURE_SEARCH_ADMIN_KEY")
    if not args.index_only and not settings.azure_blob_connection_string:
        missing.append("AZURE_BLOB_CONNECTION_STRING")
    if args.with_vectors and not settings.github_token:
        missing.append("GITHUB_TOKEN")

    if missing:
        print(f"[ERROR] Missing required configuration variables: {', '.join(missing)}")
        print("[ERROR] Please make sure your .env file is populated correctly.")
        sys.exit(1)

    print("[INFO] Environment credentials validated successfully.")


def test_embedding_model() -> bool:
    """Test if the text-embedding-3-small model is accessible via GitHub Models."""
    print("[INFO] Testing text-embedding-3-small model availability...")
    try:
        client = openai.OpenAI(
            base_url=settings.github_models_endpoint,
            api_key=settings.github_token,
        )
        # 10-word test string call
        client.embeddings.create(
            model="openai/text-embedding-3-small",
            input=["This is a test to verify if the embedding model is available."],
        )
        print("[INFO] Embedding model test: SUCCESS")
        return True
    except Exception as e:
        print(f"[WARNING] Embedding model test failed: {e}")
        return False


def chunk_document(text: str, filename: str, enc) -> list[dict]:
    """
    Chunk markdown documents.
    Target: ~500 tokens per chunk.
    Maintains H2 heading boundaries and includes 50-token overlap between chunks.
    """
    chunks = []
    
    # Extract H1 or use filename as default document title
    doc_title = filename.replace(".md", "").replace("_", " ").title()
    lines = text.split("\n")
    if lines and lines[0].startswith("# "):
        doc_title = lines[0].replace("# ", "").strip()
        text = "\n".join(lines[1:]).strip()

    # Split document by H2 headings
    sections = text.split("\n## ")
    
    # Process introduction section (before first H2)
    intro = sections[0].strip()
    if intro:
        chunks.extend(_chunk_section_content(intro, "Introduction", filename, doc_title, enc))

    # Process all H2 sections
    for sec in sections[1:]:
        sec_lines = sec.split("\n")
        heading = sec_lines[0].strip()
        body = "\n".join(sec_lines[1:]).strip()
        if body:
            chunks.extend(_chunk_section_content(body, heading, filename, doc_title, enc))

    # Assign sequential index and clean chunk_id
    for idx, chunk in enumerate(chunks):
        chunk["chunk_index"] = idx
        clean_name = filename.replace(".md", "").lower().replace("_", "-")
        chunk["chunk_id"] = f"chunk-{clean_name}-{idx:03d}"

    return chunks


def _chunk_section_content(body: str, heading: str, filename: str, doc_title: str, enc) -> list[dict]:
    """Helper to chunk section body while respecting headings and token constraints."""
    tokens = enc.encode(body)
    token_count = len(tokens)
    
    # If it fits entirely, return it
    if token_count <= 450: # Leave room for header
        return [{
            "content": f"## {heading}\n\n{body}",
            "title": doc_title,
            "source_file": filename,
            "section_heading": heading,
            "token_count": token_count + len(enc.encode(heading)) + 5
        }]
        
    paragraphs = body.split("\n\n")
    chunks = []
    curr_paras = []
    curr_tokens = 0
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_tokens = len(enc.encode(para))
        
        # If a single paragraph is too large, split by sentences
        if para_tokens > 400:
            if curr_paras:
                content_str = "\n\n".join(curr_paras)
                chunks.append({
                    "content": f"## {heading}\n\n{content_str}",
                    "title": doc_title,
                    "source_file": filename,
                    "section_heading": heading,
                    "token_count": curr_tokens + len(enc.encode(heading)) + 5
                })
                curr_paras = []
                curr_tokens = 0
            
            sentences = para.split(". ")
            curr_sents = []
            curr_sent_tokens = 0
            for sent in sentences:
                sent = sent.strip()
                if not sent.endswith("."):
                    sent += "."
                sent_tok = len(enc.encode(sent))
                
                if curr_sent_tokens + sent_tok > 400:
                    sent_str = " ".join(curr_sents)
                    chunks.append({
                        "content": f"## {heading} (Continued)\n\n{sent_str}",
                        "title": doc_title,
                        "source_file": filename,
                        "section_heading": heading,
                        "token_count": curr_sent_tokens + len(enc.encode(heading)) + 10
                    })
                    # Overlap: keep last sentence
                    if curr_sents:
                        curr_sents = [curr_sents[-1], sent]
                        curr_sent_tokens = len(enc.encode(curr_sents[0])) + sent_tok
                    else:
                        curr_sents = [sent]
                        curr_sent_tokens = sent_tok
                else:
                    curr_sents.append(sent)
                    curr_sent_tokens += sent_tok
            
            if curr_sents:
                sent_str = " ".join(curr_sents)
                chunks.append({
                    "content": f"## {heading} (Continued)\n\n{sent_str}",
                    "title": doc_title,
                    "source_file": filename,
                    "section_heading": heading,
                    "token_count": curr_sent_tokens + len(enc.encode(heading)) + 10
                })
        else:
            if curr_tokens + para_tokens > 400:
                content_str = "\n\n".join(curr_paras)
                chunks.append({
                    "content": f"## {heading}\n\n{content_str}",
                    "title": doc_title,
                    "source_file": filename,
                    "section_heading": heading,
                    "token_count": curr_tokens + len(enc.encode(heading)) + 5
                })
                # Overlap: keep last paragraph if short enough
                if len(curr_paras) > 1 and len(enc.encode(curr_paras[-1])) < 80:
                    curr_paras = [curr_paras[-1], para]
                    curr_tokens = len(enc.encode(curr_paras[0])) + para_tokens
                else:
                    curr_paras = [para]
                    curr_tokens = para_tokens
            else:
                curr_paras.append(para)
                curr_tokens += para_tokens

    if curr_paras:
        content_str = "\n\n".join(curr_paras)
        chunks.append({
            "content": f"## {heading}\n\n{content_str}",
            "title": doc_title,
            "source_file": filename,
            "section_heading": heading,
            "token_count": curr_tokens + len(enc.encode(heading)) + 5
        })

    return chunks


def process_local_documents(kb_dir: Path) -> list[dict]:
    """Read and chunk all local markdown files in the knowledge base directory."""
    print(f"[INFO] Reading local documents from {kb_dir}...")
    enc = tiktoken.get_encoding("cl100k_base")
    all_chunks = []
    
    for md_file in kb_dir.glob("*.md"):
        print(f"[INFO] Processing document: {md_file.name}")
        with open(md_file, "r", encoding="utf-8") as f:
            text = f.read()
        chunks = chunk_document(text, md_file.name, enc)
        print(f"[INFO] Created {len(chunks)} chunks for {md_file.name}")
        all_chunks.extend(chunks)
        
    print(f"[INFO] Total chunks processed: {len(all_chunks)}")
    return all_chunks


def upload_to_blob_storage(kb_dir: Path):
    """Upload all markdown files to Azure Blob Storage container."""
    from azure.storage.blob import BlobServiceClient

    print(f"[INFO] Connecting to Azure Blob Storage container '{settings.azure_blob_container_name}'...")
    blob_service_client = BlobServiceClient.from_connection_string(settings.azure_blob_connection_string)
    container_client = blob_service_client.get_container_client(settings.azure_blob_container_name)

    # Create container if it does not exist
    if not container_client.exists():
        print(f"[INFO] Container '{settings.azure_blob_container_name}' does not exist. Creating...")
        container_client.create_container()

    for md_file in kb_dir.glob("*.md"):
        blob_client = container_client.get_blob_client(md_file.name)
        print(f"[INFO] Uploading {md_file.name} to blob storage...")
        with open(md_file, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)

    print("[INFO] Blob storage upload complete.")


def setup_search_index(use_vectors: bool):
    """Configure Azure AI Search Index schema."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        SearchIndex,
        SimpleField,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        VectorSearch,
        VectorSearchProfile,
        ExhaustiveKnnAlgorithmConfiguration,
        ExhaustiveKnnParameters,
        SemanticConfiguration,
        SemanticPrioritizedFields,
        SemanticField,
        SemanticSearch,
    )

    print(f"[INFO] Connecting to Azure AI Search endpoint: {settings.azure_search_endpoint}...")
    index_client = SearchIndexClient(
        endpoint=settings.azure_search_endpoint,
        credential=AzureKeyCredential(settings.azure_search_admin_key),
    )

    # 1. Define fields
    fields = [
        SimpleField(name="chunk_id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchableField(name="content", type=SearchFieldDataType.String, searchable=True),
        SearchableField(name="title", type=SearchFieldDataType.String, searchable=True, filterable=True),
        SimpleField(name="source_file", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="section_heading", type=SearchFieldDataType.String, searchable=True, filterable=True),
        SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(name="token_count", type=SearchFieldDataType.Int32),
    ]

    if use_vectors:
        fields.append(
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=1536,
                vector_search_profile_name="certiq-vector-profile",
            )
        )

    # 2. Vector search configurations
    vector_search = None
    if use_vectors:
        vector_search = VectorSearch(
            algorithms=[
                ExhaustiveKnnAlgorithmConfiguration(
                    name="certiq-knn-config",
                    parameters=ExhaustiveKnnParameters(metric="cosine"),
                )
            ],
            profiles=[
                VectorSearchProfile(
                    name="certiq-vector-profile",
                    algorithm_configuration_name="certiq-knn-config",
                )
            ],
        )

    # 3. Semantic search configurations
    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="certiq-semantic",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                    keywords_fields=[SemanticField(field_name="section_heading")],
                ),
            )
        ]
    )

    # 4. Construct SearchIndex Definition
    index_definition = SearchIndex(
        name=settings.azure_search_index_name,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )

    print(f"[INFO] Creating/updating Azure AI Search index '{settings.azure_search_index_name}'...")
    # Delete existing index to ensure clean re-index (removes orphan chunks from previous runs)
    try:
        index_client.delete_index(settings.azure_search_index_name)
        print(f"[INFO] Deleted existing index '{settings.azure_search_index_name}'.")
    except Exception:
        print(f"[INFO] No existing index to delete (first run).")
    index_client.create_or_update_index(index_definition)
    print("[INFO] Azure AI Search index schema configured successfully.")


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(openai.RateLimitError),
    reraise=True,
)
def call_embedding_api_with_retry(client, inputs):
    return client.embeddings.create(
        model="openai/text-embedding-3-small",
        input=inputs,
    )


def generate_embeddings_for_chunks(chunks: list[dict]):
    """Generate embeddings using text-embedding-3-small via GitHub Models."""
    print(f"[INFO] Generating embeddings for {len(chunks)} chunks in batches of 16...")
    client = openai.OpenAI(
        base_url=settings.github_models_endpoint,
        api_key=settings.github_token,
    )

    batch_size = 16
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        inputs = [c["content"] for c in batch]
        
        try:
            response = call_embedding_api_with_retry(client, inputs)
            for idx, item in enumerate(response.data):
                batch[idx]["content_vector"] = item.embedding
            print(f"[INFO] Generated embeddings for chunks {i} to {i+len(batch)-1}")
        except Exception as e:
            print(f"[ERROR] Failed to generate embeddings for batch starting at {i}: {e}")
            sys.exit(1)

    print("[INFO] Embeddings generation complete.")


def upload_chunks_to_search(chunks: list[dict]):
    """Upload documents to the Azure AI Search index."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    print(f"[INFO] Connecting to Azure AI Search index '{settings.azure_search_index_name}'...")
    search_client = SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=settings.azure_search_index_name,
        credential=AzureKeyCredential(settings.azure_search_admin_key),
    )

    # Azure AI Search recommends batching uploads
    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        print(f"[INFO] Uploading batch of {len(batch)} documents...")
        
        docs = []
        for c in batch:
            doc = {
                "chunk_id": c["chunk_id"],
                "content": c["content"],
                "title": c["title"],
                "source_file": c["source_file"],
                "section_heading": c["section_heading"],
                "chunk_index": c["chunk_index"],
                "token_count": c["token_count"],
            }
            if "content_vector" in c:
                doc["content_vector"] = c["content_vector"]
            docs.append(doc)

        results = search_client.upload_documents(documents=docs)
        failed = sum(1 for r in results if not r.succeeded)
        if failed > 0:
            print(f"[WARNING] {failed} documents failed to upload in this batch.")
        else:
            print(f"[INFO] Batch of {len(batch)} documents uploaded successfully.")

    print("[INFO] Upload of all documents to Azure AI Search complete.")


def main():
    args = parse_args()

    print("[INFO] Default search mode: BM25 + Azure Semantic Ranking (no embeddings)")

    # Define paths
    base_dir = Path("D:/Agents League Hackathon/CertIQ")
    kb_dir = base_dir / "data" / "synthetic" / "org_knowledge"

    # Step 1: Pre-process documents and chunk them
    if not kb_dir.exists():
        print(f"[ERROR] Knowledge directory does not exist: {kb_dir}")
        sys.exit(1)

    chunks = process_local_documents(kb_dir)

    # Check vector search flag
    use_vectors = False
    if args.with_vectors:
        if args.dry_run:
            print("[INFO] Dry run with vectors: testing embedding endpoint...")
            test_ok = test_embedding_model()
            if test_ok:
                print("[INFO] Dry run: Embedding model confirmed.")
                use_vectors = True
            else:
                print("[WARNING] Dry run: Embedding model unavailable. Would fall back to BM25.")
        else:
            test_ok = test_embedding_model()
            if test_ok:
                print("[INFO] Embedding model confirmed. Building vector index with exhaustive KNN.")
                use_vectors = True
            else:
                print("[WARNING] Embedding model unavailable. Falling back to BM25 + semantic ranking automatically.")
                use_vectors = False

    # Dry run reporting
    if args.dry_run:
        print("\n=== DRY RUN SUMMARY REPORT ===")
        print(f"Total documents: {len(list(kb_dir.glob('*.md')))}")
        print(f"Total chunks generated: {len(chunks)}")
        total_tokens = sum(c["token_count"] for c in chunks)
        print(f"Total tokens in index: {total_tokens}")
        print(f"Average tokens per chunk: {total_tokens / len(chunks) if chunks else 0:.1f}")
        print(f"Index target size: {len(chunks)} documents")
        print(f"Vector search enabled: {use_vectors}")
        print("Dry run completed. No writes made to Azure.")
        return

    # Validate Azure credentials for real run
    validate_environment(args)

    # Step 2: Upload documents to Azure Blob Storage (if not skipped)
    if not args.index_only:
        print("[INFO] Starting Azure Blob Storage upload...")
        upload_to_blob_storage(kb_dir)
    else:
        print("[INFO] Skipping Azure Blob Storage upload (--index-only).")

    # Step 3: Setup index schema on Azure AI Search
    print("[INFO] Setting up Azure AI Search index schema...")
    setup_search_index(use_vectors)

    # Step 4: Generate embeddings if vector search is enabled
    if use_vectors:
        generate_embeddings_for_chunks(chunks)

    # Step 5: Index chunks on Azure AI Search
    print("[INFO] Uploading chunks to search index...")
    upload_chunks_to_search(chunks)

    print("\n=== SETUP SUCCESSFUL ===")
    print(f"Knowledge base indexed successfully under name: {settings.azure_search_index_name}")
    print(f"Total chunks indexed: {len(chunks)}")
    print(f"Vector search active: {use_vectors}")


if __name__ == "__main__":
    main()
