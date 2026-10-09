import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

DB_DIR = "netops/rag/chroma_db"

# 30 Evaluation Questions mapping to expected Source ID prefixes
QA_PAIRS = [
    # FRR OSPF Docs
    ("How do I configure an OSPF passive interface?", "ospfd-interfaces"),
    ("What command sets the OSPF SPF throttle timers?", "ospfd-routers"),
    ("How do I configure an OSPF area?", "ospfd-interfaces"),
    ("How do I redistribute static routes into OSPF?", "ospfd-routers"),
    ("How to set the OSPF router ID?", "ospfd-routers"),
    ("Command to show OSPF neighbors?", "ospfd-showing-ospf-informati"),
    ("How do I disable OSPF on an interface?", "ospfd-interfaces"),
    ("How to configure OSPF authentication?", "ospfd-interfaces"),
    
    # FRR BGP Docs
    ("What is the BGP route selection process in FRR?", "bgp-route-selection"),
    ("How do I configure a BGP neighbor remote AS?", "bgp-routers"),
    ("Command to show BGP summary?", "bgp-displaying-bgp-routing"),
    ("How to configure a BGP route map?", "bgp-routers"),
    ("How do I clear BGP sessions?", "bgp-routers"),
    ("What is a BGP peer group?", "bgp-peer-groups"),
    ("How to advertise a network in BGP?", "bgp-routers"),
    ("How do I set BGP local preference?", "bgp-routers"),
    
    # Custom Runbooks (Failures)
    ("How do I fix an OSPF area mismatch?", "failures-ospf-area-mismatch"),
    ("Why is my OSPF neighbor missing?", "failures-ospf-passive-interface"),
    
    # RFC 2328 (OSPF)
    ("What is the OSPF Link State Update packet?", "rfc2328-4.3"),
    ("What is the format of an OSPF Hello packet?", "rfc2328-a.3"),
    ("How are OSPF LSAs aged?", "rfc2328-14"),
    ("Describe the OSPF neighbor state machine.", "rfc2328-10.1"),
    ("What is a Designated Router in OSPF?", "rfc2328-7.3"),
    ("What is the OSPF Routing Table structure?", "rfc2328-11"),
    
    # RFC 4271 (BGP)
    ("What is the BGP OPEN message format?", "rfc4271-4.2"),
    ("How are BGP UPDATE messages structured?", "rfc4271-4.3"),
    ("What is the BGP FSM (Finite State Machine)?", "rfc4271-8"),
    ("Explain the BGP NOTIFICATION message.", "rfc4271-4.5"),
    ("What is the BGP Keepalive timer?", "rfc4271-4.4"),
    ("How does BGP handle path attributes?", "rfc4271-5"),
]

def main():
    print("Loading vector database and building BM25 index...")
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="BAAI/bge-small-en-v1.5")
    client = chromadb.PersistentClient(path=DB_DIR)
    collection = client.get_collection(name="netops_docs", embedding_function=emb_fn)
    
    all_data = collection.get(include=["documents", "metadatas"])
    all_docs = all_data["documents"]
    all_ids = all_data["ids"]
    all_metas = all_data["metadatas"]

    tokenized_docs = [doc.lower().split() for doc in all_docs]
    bm25 = BM25Okapi(tokenized_docs)
    
    scores = {"vector": 0, "bm25": 0, "hybrid": 0}
    k = 5

    print(f"\nEvaluating Recall@{k} across {len(QA_PAIRS)} network engineering questions...\n")

    for query, expected_prefix in QA_PAIRS:
        # 1. Vector Search
        v_resp = collection.query(query_texts=[query], n_results=k)
        v_ids = v_resp["ids"][0]
        
        # 2. BM25 Search
        t_query = query.lower().split()
        b_scores = bm25.get_scores(t_query)
        b_top = sorted(range(len(b_scores)), key=lambda i: b_scores[i], reverse=True)[:k]
        b_ids = [all_ids[i] for i in b_top]
        
        # 3. Hybrid (RRF) Search
        # Get broader pool for fusion
        v_pool = collection.query(query_texts=[query], n_results=k*2)["ids"][0]
        b_pool = [all_ids[i] for i in sorted(range(len(b_scores)), key=lambda i: b_scores[i], reverse=True)[:k*2]]
        
        rrf = {}
        for rank, doc_id in enumerate(v_pool):
            rrf[doc_id] = rrf.get(doc_id, 0) + 1 / (rank + 60)
        for rank, doc_id in enumerate(b_pool):
            rrf[doc_id] = rrf.get(doc_id, 0) + 1 / (rank + 60)
            
        h_ids = [doc_id for doc_id, _ in sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:k]]
        
        # Grade results (prefix match allows us to ignore dynamic chunk suffixes like -0, -1)
        if any(expected_prefix in vid for vid in v_ids): scores["vector"] += 1
        if any(expected_prefix in bid for bid in b_ids): scores["bm25"] += 1
        if any(expected_prefix in hid for hid in h_ids): scores["hybrid"] += 1

    total = len(QA_PAIRS)
    print("-" * 40)
    print("RETRIEVAL EVALUATION RESULTS (Recall@5)")
    print("-" * 40)
    print(f"Vector Only: {scores['vector']}/{total} ({(scores['vector']/total)*100:.1f}%)")
    print(f"BM25 Only:   {scores['bm25']}/{total} ({(scores['bm25']/total)*100:.1f}%)")
    print(f"Hybrid RRF:  {scores['hybrid']}/{total} ({(scores['hybrid']/total)*100:.1f}%)")
    print("-" * 40)

if __name__ == "__main__":
    main()
