# Moncey Concierge

**Live at:** https://concierge.aws.monce.ai
**Chat UI:** https://concierge.aws.monce.ai/ui

Internal memory and intelligence layer for Monce AI. Tracks extraction pipeline activity, answers analytical questions from pre-computed digests, and bridges to Snake for synonym management.

## Architecture

```
Route53 → EC2 (nginx/SSL → gunicorn) → FastAPI + Bedrock Sonnet
                                              │
                         ┌────────────────────┼──────────────────┐
                    Memory (JSON)        monce_db (S3)     snake.aws.monce.ai
                    - memories.json      - extractions      - article synonyms
                    - conversations.json - stats            - client synonyms
                    - digests.json                          - rebuild triggers
```

## Quick Start

```bash
# Chat
curl -X POST https://concierge.aws.monce.ai/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "What are the top clients this week?"}'

# Ingest last 14 days of extractions
curl -X POST https://concierge.aws.monce.ai/ingest \
  -H 'Content-Type: application/json' \
  -d '{"days": 14}'

# Search memories
curl 'https://concierge.aws.monce.ai/search?q=SGD'

# Add article synonym to Snake
curl -X POST https://concierge.aws.monce.ai/snake/synonym \
  -H 'Content-Type: application/json' \
  -d '{"text": "6mm", "num_article": "1006", "factory_id": "3"}'

# Add client synonym to Snake
curl -X POST https://concierge.aws.monce.ai/snake/synonym_client \
  -H 'Content-Type: application/json' \
  -d '{"text": "DUBOS MATERIAUX", "numero_client": "565", "factory_id": "4"}'
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service health + memory/conversation counts |
| `/ui` | GET | Chat interface |
| `/chat` | POST | Chat with Concierge (Sonnet + context) |
| `/remember` | POST | Store a memory manually |
| `/forget` | POST | Forget memories matching query |
| `/memories` | GET | List memories (paginated, filterable by `?tag=`) |
| `/search` | GET | Keyword search across memories (`?q=`) |
| `/ingest` | POST | Pull extractions from monce_db into memory |
| `/ingest/stats` | GET | Pull aggregate stats from monce_db |
| `/digest` | POST | Recompute aggregate digests |
| `/digest` | GET | Return current digests |
| `/snake/synonym` | POST | Push article synonym to Snake |
| `/snake/synonym_client` | POST | Push client synonym to Snake |
| `/snake/synonyms_batch` | POST | Batch push synonyms + rebuild |
| `/snake/rebuild` | POST | Trigger Snake rebuild_all |

## How Concierge Answers Questions

Concierge uses a 3-layer context system so Sonnet can answer precisely:

1. **Digests** — Pre-computed aggregates from ALL extraction data (top clients, daily volumes, glass types, matching quality, weekly rankings). Always included. Compact.
2. **Search results** — Memories keyword-matched to the user's question (up to 20). Targeted.
3. **Recent memories** — Last 10 raw ingestions. For "what just happened" questions.

When you call `/ingest`, digests are auto-recomputed. You can also manually trigger `/digest` POST.

## Feeding Data to Concierge

### From monce_db (extractions)

```bash
# Ingest last 14 days, all factories
curl -X POST https://concierge.aws.monce.ai/ingest \
  -d '{"days": 14}'

# Ingest specific factory
curl -X POST https://concierge.aws.monce.ai/ingest \
  -d '{"days": 14, "factory": "VIP"}'

# Only verified extractions
curl -X POST https://concierge.aws.monce.ai/ingest \
  -d '{"days": 14, "status": "verified"}'
```

Deduplicates by extraction ID — safe to call repeatedly.

### Manual memories

```bash
# Remember something
curl -X POST https://concierge.aws.monce.ai/remember \
  -d '{"text": "Factory 4 had a major outage today", "tags": ["incident", "VIP"]}'
```

### Programmatic best practices

To make Concierge the effective memory of Monce AI:

1. **Tag everything.** Tags enable filtering and weighted search. Use consistent tags: `extraction`, `synonym`, `incident`, factory names.

2. **Ingest regularly.** Set up a cron or call `/ingest` daily. Concierge deduplicates, so overcalling is fine.

3. **Use `/remember` for non-extraction events.** Deployments, incidents, configuration changes — anything Sonnet should know about when answering questions.

4. **Let digests do the heavy lifting.** Don't ask Concierge to count raw memories — digests pre-compute totals, rankings, and trends. If you need a new aggregate, add it to `compute_digests()` in `memory.py`.

5. **Search before asking.** For programmatic lookups, use `/search?q=keyword` instead of `/chat`. It's faster and doesn't consume Bedrock tokens.

## Snake Synonym Integration

Concierge can push synonyms directly to snake.aws.monce.ai (article matching service). This is useful when extraction analysis reveals missing or incorrect synonym mappings.

### Article synonyms

```bash
curl -X POST https://concierge.aws.monce.ai/snake/synonym \
  -d '{"text": "PLANILUX 4MM", "num_article": "1004", "factory_id": "3"}'
```

### Client synonyms

```bash
curl -X POST https://concierge.aws.monce.ai/snake/synonym_client \
  -d '{"text": "SAINT GOBAIN PARIS", "numero_client": "7890", "factory_id": "4"}'
```

### Batch workflow

```bash
# Push multiple synonyms without rebuilding each time
curl -X POST https://concierge.aws.monce.ai/snake/synonyms_batch \
  -d '{
    "synonym_type": "article",
    "synonyms": [
      {"text": "6mm", "num_article": "1006", "factory_id": "3"},
      {"text": "FLOAT 6", "num_article": "1006", "factory_id": "3"},
      {"text": "8mm clair", "num_article": "1008", "factory_id": "4"}
    ]
  }'
```

Batch adds all synonyms with `trigger_rebuild=false`, then calls `/rebuild_all` once at the end.

Every synonym action is logged as a Concierge memory with tags `[synonym, article/client, factory_id]`.

## Claude Code Sync

To work on Concierge with Claude Code:

```bash
git clone git@github.com:Monce-AI/concierge.aws.monce.ai.git
cd concierge.aws.monce.ai
```

### File structure

```
concierge.aws.monce.ai/
  api/
    __init__.py
    main.py          # FastAPI app entry
    config.py        # Env var config (Bedrock, data dir)
    routes.py        # All endpoints
    sonnet.py        # Bedrock Sonnet caller + system prompt
    memory.py        # Memory CRUD + digest engine + search
    ingest.py        # monce_db ingestion
    snake.py         # Snake API client (synonyms + rebuild)
    static/
      index.html     # Landing page
      ui.html        # Chat interface
  terraform/
    main.tf          # EC2 + SG + Route53
    deploy.sh        # Rsync + systemd + nginx
  setup.py
```

### Deploy

```bash
cd terraform
./deploy.sh          # or ./deploy.sh <ip>
```

### Environment variables (on server at `/opt/concierge/.env`)

```
AWS_BEARER_TOKEN_BEDROCK=...   # Bedrock access
MONCE_S3_ACCESS_KEY=...        # monce_db S3 access
MONCE_S3_SECRET_KEY=...        # monce_db S3 secret
```

### Adding new capabilities

1. **New data source:** Add an ingestion function in `ingest.py`, add a route in `routes.py`
2. **New digest type:** Add computation logic in `memory.py` → `compute_digests()`
3. **New external service:** Create a module (like `snake.py`), add routes
4. **Changing Sonnet's behavior:** Edit `SYSTEM_PROMPT` in `sonnet.py`

## Infrastructure

| | Spec |
|---|---|
| Instance | t3.small (2 vCPU, 2 GB) |
| Region | eu-west-3 (Paris) |
| IP | 35.180.24.206 |
| Workers | 2 gunicorn/uvicorn |
| Timeout | 300s (for heavy ingestion) |
| SSL | Let's Encrypt via certbot |
| Model | Bedrock Sonnet 3 (bearer token) |
