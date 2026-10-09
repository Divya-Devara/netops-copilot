import os
import re
import chromadb
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter

CORPUS_DIR = "netops/rag/corpus"
DB_DIR = "netops/rag/chroma_db"

def process_file(filename: str):
    with open(os.path.join(CORPUS_DIR, filename), "r", encoding="utf-8") as f:
        text = f.read()
    
    sections = []
    curr_id = "0"
    curr_text = []
    is_rfc = filename.startswith("rfc")
    lines = text.splitlines()
    
    # Pass 1: Parse headings and numbered sections
    for i, line in enumerate(lines):
        header_match = False
        new_id = curr_id
        
        if is_rfc:
            # Match RFC sections like "10.3. " or "10.3 "
            m = re.match(r'^(\d+(?:\.\d+)*)\.?\s+[A-Z]', line)
            if m and not line.startswith(" ") and not line.startswith("\t"):
                new_id = m.group(1)
                header_match = True
        else:
            # Match Markdown (#) or RST (--- / ===) headers
            m = re.match(r'^(#+)\s+(.*)', line)
            if m:
                new_id = m.group(2).strip().lower().replace(" ", "-")[:25]
                header_match = True
            elif i > 0 and re.match(r'^(=+|-+)$', line) and len(line) >= len(lines[i-1].strip()) and lines[i-1].strip():
                new_id = lines[i-1].strip().lower().replace(" ", "-")[:25]
                header_match = True
                if len(curr_text) > 0:
                    curr_text.pop() # Remove the text line that became the header

        if header_match and curr_text:
            sections.append((curr_id, "\n".join(curr_text)))
            curr_text = []
            curr_id = new_id

        curr_text.append(line)

    if curr_text:
        sections.append((curr_id, "\n".join(curr_text)))

    # Pass 2: Token-aware chunking (300-800 tokens, 50 overlap)
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        separators=["\n```", "\n\n", "\n", " "], 
        chunk_size=600,
        chunk_overlap=50
    )

    docs, metadatas, ids = [], [], []
    source_name = filename.split('.')[0]
    seen_ids = set()
    
    for sec_id, sec_text in sections:
        chunks = splitter.split_text(sec_text)
        for j, chunk in enumerate(chunks):
            base_id = f"{source_name}-{sec_id}-{j}"
            stable_id = base_id
            counter = 1
            # Ensure globally unique ID if docs have duplicate headers
            while stable_id in seen_ids:
                stable_id = f"{base_id}-{counter}"
                counter += 1
            seen_ids.add(stable_id)
            
            docs.append(chunk)
            metadatas.append({"source": source_name, "section": sec_id, "stable_id": stable_id})
            ids.append(stable_id)
            
    return docs, metadatas, ids

def main():
    print("Initializing embedding model (BAAI/bge-small-en-v1.5)...")
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="BAAI/bge-small-en-v1.5")
    
    print(f"Creating persistent ChromaDB at {DB_DIR}...")
    client = chromadb.PersistentClient(path=DB_DIR)
    
    # Clean up the failed partial run before starting fresh
    try:
        client.delete_collection(name="netops_docs")
    except ValueError:
        pass
        
    collection = client.create_collection(name="netops_docs", embedding_function=emb_fn)

    all_docs, all_metas, all_ids = [], [], []
    for file in os.listdir(CORPUS_DIR):
        if file.endswith((".txt", ".rst", ".md")):
            print(f"Structuring {file}...")
            d, m, i = process_file(file)
            all_docs.extend(d)
            all_metas.extend(m)
            all_ids.extend(i)
            
    print(f"Ingesting {len(all_docs)} chunks into vector database...")
    batch_size = 2000
    for i in range(0, len(all_docs), batch_size):
        collection.add(
            documents=all_docs[i:i+batch_size],
            metadatas=all_metas[i:i+batch_size],
            ids=all_ids[i:i+batch_size]
        )
    print("Ingestion complete. Database is ready.")

if __name__ == "__main__":
    main()
