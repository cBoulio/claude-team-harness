---
title: Choosing a vector store for a small team
date: 2026-10-01
author: researcher
status: final
tags: search, embeddings, databases, sample
summary: If you already run Postgres, start with pgvector. Reach for a dedicated vector database only when you outgrow it or need features Postgres can't give you.
---

# Choosing a vector store for a small team

> [!NOTE]
> This is a sample dossier that ships with the template to show what the research renderer
> produces. The team and workload are fictional. Check current docs and pricing before relying
> on any of it.

## Bottom line

- The fictional team (four engineers, one Postgres database, about 2 million chunks of support
  articles and tickets) does not need a new database to get good semantic search.
- **pgvector** keeps embeddings next to the rows they describe, so filters, joins, backups, and
  access control stay in one place [1].
- **sqlite-vec** is a good fit for local tools, CLIs, and tests where a server is overkill [2].
- A dedicated engine (**Qdrant**, **Chroma**, or a managed service like **Pinecone**) earns its
  keep when the corpus or query load grows well past what one Postgres instance handles
  comfortably, or when you need features like built-in hybrid scoring or multi-tenant
  collections out of the box [3][4][5].
- Whatever you pick, put retrieval behind a small interface so you can swap the store later.

> [!VERDICT]
> Start with pgvector and an HNSW index on the existing Postgres. Re-evaluate when p95 query
> latency or index build time stops meeting the target, not before.

## What the team needs

| Requirement | Detail | Weight |
|-------------|--------|-------:|
| Corpus size | about 2M chunks today, growing roughly 30% a year | high |
| Latency | p95 under 150 ms for top-10 retrieval | high |
| Filtering | by product, customer tier, and date | high |
| Operations | no new on-call surface if avoidable | high |
| Hybrid search | keyword plus vector ranking | medium |
| Budget | modest; prefer existing infrastructure | medium |

## Options compared

| Option | What it is | Fits when | Watch out for |
|--------|------------|-----------|---------------|
| pgvector | Postgres extension with vector types and HNSW / IVFFlat indexes [1] | You already run Postgres and want one source of truth | Index memory, build time on large tables, tuning `ef_search` |
| sqlite-vec | SQLite extension for vector search [2] | Local tools, embedded apps, test fixtures | Single-writer database; not a shared service |
| Qdrant | Open-source vector database with filtering and payloads; managed cloud available [3] | Large corpora, heavy filtering, dedicated search service | Another system to run, back up, and secure |
| Chroma | Open-source embedding database, easy to embed in Python apps [4] | Prototypes and small services | Check production deployment options for your scale |
| Pinecone | Fully managed vector database [5] | You want zero operations and accept a vendor | Data residency, cost at scale, lock-in |

### Why pgvector first

Most of the team's queries filter by product and customer tier before ranking by similarity.
With pgvector those filters are ordinary `WHERE` clauses on the same table, and permissions
follow the rules the app already has. A dedicated store would need those attributes copied
into its payloads and kept in sync.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE chunks ADD COLUMN embedding vector(1024);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);

SELECT id, title
FROM chunks
WHERE product = 'billing' AND tier = 'enterprise'
ORDER BY embedding <=> $1
LIMIT 10;
```

> [!TIP]
> Build the HNSW index after the initial bulk load, not before, and raise
> `maintenance_work_mem` for the build. Both cut index build time noticeably [1].

### When to move off it

Plan a move to a dedicated engine if any of these hold for more than a few weeks:

1. p95 retrieval latency exceeds the target after index tuning.
2. Index builds or vacuum on the embeddings table interfere with the app's normal traffic.
3. You need per-tenant isolation or replication patterns that are awkward in Postgres.

> [!RISK]
> Embeddings from different models are not interchangeable. Changing the embedding model means
> re-embedding the whole corpus, whichever store you use. Record the model name and version
> with every vector.

## Hybrid search

Keyword matching still wins for exact identifiers such as error codes and SKUs. In Postgres,
combine a full-text `tsvector` rank with vector similarity and merge the two result lists
(reciprocal rank fusion is a simple, robust choice). Dedicated engines often provide this
directly; check that their scoring is explainable enough for your support team.

> [!WARNING]
> Don't judge options on public benchmark charts alone. Run your own queries against a
> sample of your own data, with your filters, and measure recall against a small labeled set.

## Recommended next steps

1. Enable pgvector on a staging copy and embed a 10% sample of the corpus.
2. Label 50 real support queries with the articles that should come back.
3. Measure recall at 10 and p95 latency with and without filters; tune `ef_search`.
4. Wrap retrieval in a `search(query, filters)` function so the store is replaceable.
5. Log the result as an issue if it misses the target, and revisit Qdrant as the first alternative.

## Sources

1. pgvector README, https://github.com/pgvector/pgvector (accessed 2026-10-01)
2. sqlite-vec README, https://github.com/asg017/sqlite-vec (accessed 2026-10-01)
3. Qdrant documentation, https://qdrant.tech/documentation/ (accessed 2026-10-01)
4. Chroma documentation, https://docs.trychroma.com/ (accessed 2026-10-01)
5. Pinecone documentation, https://docs.pinecone.io/ (accessed 2026-10-01)
