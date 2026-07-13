# Swapping the Vector DB: Elasticsearch (default) → ChromaDB (alternative)

**Status:** documented migration path (not applied — Elasticsearch remains the default).
**Audience:** a developer who wants Sherlock's RAG knowledge layer on ChromaDB instead of Elasticsearch.
**Scope:** this is the *vector* store used by the RAG Blueprint (document retrieval / FRAG). The
graph store (Neo4j) is a separate swap — see
[SWAP_GRAPH_DB_NEO4J_TO_FALKORDB.md](SWAP_GRAPH_DB_NEO4J_TO_FALKORDB.md).

---

## ⚠️ Read this first: ChromaDB is not a built-in backend in RAG Blueprint 2.6.0

Sherlock's knowledge layer is **NVIDIA RAG Blueprint 2.6.0** (cloned into `external/rag/`).
Its vector store is selected by one env var, `APP_VECTORSTORE_NAME`, dispatched here:

> [external/rag/src/nvidia_rag/utils/vdb/__init__.py](../external/rag/src/nvidia_rag/utils/vdb/__init__.py) — function `_get_vdb_op`
> - `:65` `if name == "milvus":` → `MilvusVDB`
> - `:106` `elif name == "elasticsearch":` → `ElasticVDB`
> - `:123` `elif name == "lancedb":` → `LanceDBVDB`
> - `:137` `else: raise ValueError(f"Invalid vector store name: …")`

**The only accepted values are `milvus`, `elasticsearch`, `lancedb`.** The strings `chroma` /
`chromadb` appear **nowhere** in the blueprint source. There is no plugin/registry mechanism.

So "swap to ChromaDB" is **not a config toggle** — it requires writing a new `ChromaVDB` adapter
class and adding a dispatch branch. Under this repo's rule *"never edit blueprint source"*
([.claude/CLAUDE.md](../.claude/CLAUDE.md) rule 4), that is a **fork / custom-code path**, and the
change lives in a maintained overlay, not in-place edits you'll lose on the next blueprint pull.

### Recommendation before you commit to ChromaDB
If your goal is simply *"a lighter / embedded / non-Elasticsearch vector store,"* the RAG Blueprint
already gives you two **zero-code, config-only** options:

| Backend | `APP_VECTORSTORE_NAME` | Nature | When to pick it |
|---|---|---|---|
| **LanceDB** | `lancedb` | Embedded, file-based, no server container. Pure-Python, ARM-friendly. | **Recommended lightweight swap** — closest in spirit to ChromaDB, but *natively supported*. Great on memory-constrained boxes (e.g. DGX Spark). |
| **Milvus** | `milvus` | Dedicated vector DB, GPU-capable (`GPU_CAGRA`). | Production scale / GPU indexing. |
| Elasticsearch | `elasticsearch` | Default; hybrid (dense+sparse) search. | Current default. |

**If you specifically need ChromaDB** (e.g. an existing Chroma deployment or Chroma-only tooling),
continue to §3 for the custom-adapter path. Otherwise, §2 (LanceDB) is a 2-line change and is the
honest "easy" answer to *"swap the vector DB."*

---

## 1. What selects / uses the vector store today

`APP_VECTORSTORE_NAME` is read by the config schema
([external/rag/src/nvidia_rag/utils/configuration.py](../external/rag/src/nvidia_rag/utils/configuration.py),
class `VectorStoreConfig`, `:126-130`) and both servers obtain their DB handle through the single
factory `_get_vdb_op()`. Defaults live in the two compose files:

| Var | rag-server | ingestor-server | Meaning |
|---|---|---|---|
| `APP_VECTORSTORE_NAME` | `docker-compose-rag-server.yaml:40` | `docker-compose-ingestor-server.yaml:39` | backend selector (default `elasticsearch`) |
| `APP_VECTORSTORE_URL` | `:37` | `:36` | default `http://elasticsearch:9200` |
| `COLLECTION_NAME` | `:67` | `:63` | default **`multimodal_data`** (Sherlock's collection) |

The Elasticsearch container starts by default via a compose profile
([external/rag/deploy/compose/vectordb.yaml](../external/rag/deploy/compose/vectordb.yaml)`:127`,
`profiles: ["", "elasticsearch"]`). The ARM64 overrides in this repo
(`deploy/compose.ingestor.arm64.override.yaml`, `deploy/compose.rag-server.arm64.override.yaml`)
do **not** touch vector-store config — so a backend swap needs no ARM-override edits.

Ingestion (ingestor-server → nv-ingest → VDB) and retrieval (rag-server → VDB) both route through
`_get_vdb_op()`; the ES implementation is
[external/rag/src/nvidia_rag/utils/vdb/elasticsearch/elastic_vdb.py](../external/rag/src/nvidia_rag/utils/vdb/elasticsearch/elastic_vdb.py)
(class `ElasticVDB`, LangChain `ElasticsearchStore`).

---

## 2. The easy, supported swap: Elasticsearch → LanceDB (config only)

No code, no new container (LanceDB is embedded/file-based). Set two env vars for **both**
rag-server and ingestor-server (e.g. in the repo's `deploy/*` env plumbing or a compose override):

```bash
APP_VECTORSTORE_NAME=lancedb
# URL auto-rewrites to a local dir (configuration.py:236-240); an explicit value is optional:
# APP_VECTORSTORE_URL=/volumes/lancedb/lancedb
```

Mount a volume for `/volumes/lancedb` so the index persists, drop the `elasticsearch` service from
the compose `up`, re-ingest `data/cases/*`, and you're done. This is the recommended path if you
just want off Elasticsearch.

> Caveats: LanceDB is the **only** backend supported by the blueprint's in-process (NRL) ingestion
> mode ([ingestor_server/main.py](../external/rag/src/nvidia_rag/ingestor_server/main.py)`:165-169`);
> and "Lite" mode forces `milvus` (`:157-163`). For the standard nv-ingest pipeline Sherlock uses,
> `lancedb` works as a normal `APP_VECTORSTORE_NAME` value.

---

## 3. The ChromaDB path (custom adapter — required, since 2.6.0 has no built-in)

To actually run ChromaDB you must add a backend adapter. Keep it in a maintained overlay so a
blueprint re-pull doesn't wipe it.

### 3a. Write a `ChromaVDB` adapter
Mirror the interface of `ElasticVDB`
([external/rag/src/nvidia_rag/utils/vdb/elasticsearch/elastic_vdb.py](../external/rag/src/nvidia_rag/utils/vdb/elasticsearch/elastic_vdb.py))
— the methods the blueprint calls on a VDB handle (create/collection management, `write_to_index`,
the LangChain retriever/`get_langchain_vectorstore`, and nv-ingest record cleanup). LangChain ships
a Chroma vector store (`langchain_chroma.Chroma`), so the adapter largely wraps that, matching the
embedding dimension the blueprint already uses.

```
external/rag/src/nvidia_rag/utils/vdb/chromadb/chroma_vdb.py   # class ChromaVDB(VDBRag)
```

### 3b. Add the dispatch branch
In [external/rag/src/nvidia_rag/utils/vdb/__init__.py](../external/rag/src/nvidia_rag/utils/vdb/__init__.py),
after the `lancedb` branch (`:123`):

```python
elif config.vector_store.name == "chromadb":
    from nvidia_rag.utils.vdb.chromadb.chroma_vdb import ChromaVDB
    return ChromaVDB(...)   # same constructor args pattern as ElasticVDB
```

### 3c. Add the ChromaDB service + profile
In [external/rag/deploy/compose/vectordb.yaml](../external/rag/deploy/compose/vectordb.yaml),
alongside the `elasticsearch` block:

```yaml
  chromadb:
    container_name: chromadb
    image: chromadb/chroma:latest      # pin a tag
    ports:
      - "8000:8000"
    volumes:
      - rag-vol-chromadb:/chroma/chroma
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/api/v2/heartbeat"]
      interval: 10s
      timeout: 2s
      retries: 10
    profiles: ["chromadb"]
# volumes: rag-vol-chromadb: { name: rag-vol-chromadb }
```

> Note the port collision risk: the RAG blueprint uses `:8000` internally in places and Sherlock
> maps AI-Q to host `:8100`; give ChromaDB a distinct host port if needed.

### 3d. Select it
Set for **both** servers, and start the chroma profile instead of elasticsearch:

```bash
APP_VECTORSTORE_NAME=chromadb
APP_VECTORSTORE_URL=http://chromadb:8000
```

---

## 4. For reference: the Elasticsearch service being replaced

[external/rag/deploy/compose/vectordb.yaml](../external/rag/deploy/compose/vectordb.yaml)`:90-127`:

```yaml
  elasticsearch:
    container_name: elasticsearch
    image: "docker.elastic.co/elasticsearch/elasticsearch:9.3.0"
    ports: ["9200:9200"]
    volumes: ["rag-vol-elasticsearch:/usr/share/elasticsearch/data"]
    environment:
      - discovery.type=single-node
      - "ES_JAVA_OPTS=-Xms1024m -Xmx1024m"
      - xpack.security.enabled=false
      - xpack.license.self_generated.type=basic
      - network.host=0.0.0.0
      - cluster.routing.allocation.disk.threshold_enabled=false
    healthcheck:
      test: ["CMD", "curl", "-s", "-f", "http://localhost:9200/_cat/health"]
      interval: 10s
      timeout: 1s
      retries: 10
    profiles: ["", "elasticsearch"]
```

---

## 5. Data migration

There's no ES→Chroma index copy. Sherlock re-ingests from source: bring up the new backend, then
re-run ingestion of `data/cases/*` (workbench upload, `phase4_audio.sh`'s `ingest_text`, or the
Phase 2/3 ingest path). Because the collection is rebuilt from the case files, nothing is lost that
can't be regenerated. Keep `COLLECTION_NAME=multimodal_data` consistent across ingestor + rag-server.

---

## 6. Verification checklist

1. Backend container healthy (LanceDB: none — file-based; ChromaDB: `/api/v2/heartbeat` ok).
2. `APP_VECTORSTORE_NAME` set identically on **both** ingestor-server and rag-server (a mismatch =
   ingest writes one store, retrieval reads another → silent empty answers).
3. Ingest a case document; confirm the collection reports vectors (backend-specific check).
4. `POST http://localhost:8100/generate` with a question answerable from the ingested doc → returns
   a **cited** "Case Documents" answer.
5. Ask the same question in the workbench chat and confirm the citation.

---

## 7. Effort summary

| Target | Effort | Nature |
|---|---|---|
| **LanceDB** | 🟢 Trivial | 2 env vars, config-only, natively supported. **Recommended** if you just want off ES. |
| **Milvus** | 🟢 Trivial | 1 env var + start `milvus` profile; GPU-capable. |
| **ChromaDB** | 🟠 Custom code | Not built-in: write `ChromaVDB` adapter + dispatch branch + compose service (overlay, not in-place). |

Bottom line: the RAG Blueprint makes vector-store swaps a config toggle **for its three supported
backends**. ChromaDB isn't one of them, so if the requirement is genuinely ChromaDB, budget for a
small adapter; if the requirement is "something lighter than Elasticsearch," use **LanceDB** and
you're done in two lines.
