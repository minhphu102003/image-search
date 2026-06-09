# Kiến trúc Hybrid GraphRAG cho Question Generation + Human-in-the-Loop

> **Nguyên tắc**: Hệ thống tách làm **2 module độc lập**, giao tiếp qua event-driven architecture.
> - **BE Nest** xử lý upload, emit event qua Redis Stream
> - **AI services** subscribe Redis Stream, xử lý background

## 1. Tổng quan - Event-Driven Architecture

```mermaid
flowchart TB
    subgraph BEFront["BE NEST (Backend)"]
        BE[BE Nest API] --> DB1[(PostgreSQL)]
        BE -->|emit event| RS[(Redis Stream)]
    end

    subgraph Module1["MODULE 1 - DOCUMENT INGEST WORKER"]
        RS -->|subscribe: doc:uploaded| M1[Document Ingest Worker]
        M1 --> A2[Parse + Chunk]
        A2 --> A3[Embed chunks + Contextual Prep -> PostgreSQL pgvector]
        A2 --> A4[LightRAG Extract Graph -> Neo4j + PostgreSQL pgvector]
        A4 --> A5[Update Document Status: READY]
    end

    subgraph Module2["MODULE 2 - QUESTION GENERATION WORKER"]
        RS -->|subscribe: question:generate| M2[Question Gen Worker]
        M2 --> D2[Hybrid Retrieval via LightRAG]
        D2 --> D3[Generator Agent LLM - Gemini]
        D3 --> D4[Validator Agent LLM - Gemini 7-dimensions]
        D4 --> D5[Human Review HITL]
        D5 --> D6[(Question Bank PostgreSQL)]
    end

    subgraph Shared["SHARED DATA STORES"]
        PG[(PostgreSQL + pgvector)]
        N4J[(Neo4j Graph DB)]
    end

    A3 --> PG
    A4 --> PG
    A4 --> N4J
    A5 --> PG
    D2 --> PG
    D2 --> N4J
```

### Redis Stream Events

| Event | Producer | Consumer | Payload |
|---|---|---|---|
| `doc:uploaded` | BE Nest | Document Ingest Worker | `{ doc_id, file_path, user_id }` |
| `doc:ingested` | Document Ingest Worker | BE Nest (callback) | `{ doc_id, status: "ready" }` |
| `question:generate` | BE Nest | Question Gen Worker | `{ doc_id, params, request_id }` |
| `question:generated` | Question Gen Worker | BE Nest (callback) | `{ request_id, questions[] }` |

---

## 2. Module 1: Document Ingest Worker

Subscribe `doc:uploaded` từ Redis Stream, xử lý background.

```mermaid
flowchart LR
    subgraph Event["1. Receive Event"]
        RS[(Redis Stream)] -->|doc:uploaded| W[Consumer Group: doc-ingest]
        W --> B[Parse payload: doc_id, file_path]
    end

    subgraph Process["2. Process"]
        B --> D[LlamaParse / MinerU]
        D --> E[Semantic Chunking 256-512 tokens]
        E --> F[Contextual Prep Anthropic pattern]
    end

    subgraph Indexing["3. Index"]
        F --> G[Embed chunks -> PostgreSQL pgvector table: document_chunks]
        F --> H[LightRAG extract entities + relationships + keywords]
        H --> I[Embed entities + relations -> PostgreSQL pgvector table: lightrag_entities, lightrag_relations]
        H --> J[Save graph nodes + edges -> Neo4j]
    end

    subgraph Done["4. Hoan tat"]
        G --> K[Update document status: READY]
        I --> K
        J --> K
        K -->|emit doc:ingested| RS
    end
```

---

## 3. Module 2: Question Generation Worker

Subscribe `question:generate` từ Redis Stream.

```mermaid
flowchart TB
    subgraph Event["Receive Event"]
        RS[(Redis Stream)] -->|question:generate| W[Consumer Group: qgen]
        W --> P[Parse payload: doc_id, params]
    end

    subgraph Retrieval["Sub-Module 2A: Hybrid Retrieval"]
        P --> A2[LightRAG query mode=mix]
        A2 --> A3[PostgreSQL pgvector: search chunks + entities + relations]
        A2 --> A4[Neo4j: graph traversal degree centrality]
        A3 & A4 --> A5[RRF Fusion + Cross-Encoder]
        A5 --> A6[Structured context: entities CSV + relations CSV + chunks]
    end

    subgraph GenValidate["Sub-Module 2B: Generate + Validate"]
        A6 --> B1[Generator Agent LLM - Gemini]
        B1 --> B2[Draft Questions]
        B2 --> B3[Validator Agent LLM - Gemini 7-dimensions]
        B3 --> B4{Score >= threshold}
        B4 -->|Yes| B5[Send to Human Review]
        B4 -->|No| B1
    end

    subgraph HITL["Sub-Module 2C: Human Review"]
        B5 --> C1[Human Review Dashboard]
        C1 --> C2{Decision}
        C2 -->|Approve| C3[(Question Bank PostgreSQL)]
        C2 -->|Edit| C4[Refine Prompt -> Generator]
        C4 --> B1
        C2 -->|Reject| C5[Discard]
    end
```

---

## 4. Sequence: Event Flow Xuyên suốt

```mermaid
sequenceDiagram
    participant User as User
    participant BE as BE Nest
    participant RS as Redis Stream
    participant Ingest as Document Ingest Worker
    participant LR as LightRAG
    participant Neo4j as Neo4j
    participant Pg as PostgreSQL pgvector
    participant QGen as Question Gen Worker
    participant Reviewer as Human Reviewer

    Note over User,Reviewer: ==== INGEST ====
    User->>BE: Upload document.pdf
    BE->>Pg: Create doc record status=processing
    BE->>RS: XADD doc:uploaded { doc_id, file_path }
    BE-->>User: 202 Accepted

    RS-->>Ingest: Consumer read doc:uploaded
    Ingest->>Ingest: Parse (LlamaParse)
    Ingest->>Ingest: Semantic chunking
    Ingest->>Ingest: Contextual prep

    par Embed chunks
        Ingest->>Pg: Store chunk vectors -> document_chunks
    and Extract graph via LightRAG
        Ingest->>LR: lightrag.insert(chunks)
        LR->>LR: LLM extract entities + relationships + keywords
        LR->>Neo4j: Save graph nodes + edges
        LR->>Pg: Save entity + relation vectors -> lightrag_entities, lightrag_relations
    end

    Ingest->>Pg: Update doc status=ready
    Ingest->>RS: XADD doc:ingested { doc_id, status: "ready" }

    Note over User,Reviewer: ==== QUESTION GENERATION ====

    User->>BE: Generate questions from doc X
    BE->>Pg: Check doc status == ready
    BE->>RS: XADD question:generate { doc_id, request_id }
    BE-->>User: 202 Accepted

    RS-->>QGen: Consumer read question:generate

    par Hybrid Retrieval via LightRAG
        QGen->>LR: lightrag.query(mode=mix)
        LR->>Pg: Vector search chunks + entities + relations
        LR->>Neo4j: Graph traversal + degree ranking
        LR-->>QGen: Return structured context
    end

    loop Retry up to 3 times
        QGen->>QGen: Generator Agent LLM (Gemini)
        QGen->>QGen: Validator Agent LLM (Gemini)
    end

    QGen->>Reviewer: Submit draft questions (PostgreSQL review_queue)
    Reviewer->>Reviewer: Approve / Edit / Reject
    Reviewer->>Pg: Save approved questions to Question Bank
```

---

## 5. Kiến trúc Deployment

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        Web[Web App] --> BEApi[BE Nest API]
    end

    subgraph Backend["BE NEST"]
        BEApi --> Pg[(PostgreSQL + pgvector)]
        BEApi --> RS[("Redis Stream")]
    end

    subgraph Workers["AI WORKERS"]
        RS -->|doc:uploaded| DocWorker[Document Ingest Worker]
        RS -->|question:generate| QGenWorker[Question Gen Worker]
        DocWorker --> Pg
        DocWorker --> Neo4j[(Neo4j)]
        DocWorker --> RS
        QGenWorker --> LightRAG[LightRAG Query Engine]
        LightRAG --> Pg
        LightRAG --> Neo4j
        QGenWorker --> Generator[Generator Agent - Gemini]
        Generator --> Validator[Validator Agent - Gemini]
        Validator --> ReviewQ[(Review Queue)]
        QGenWorker --> RS
    end

    subgraph HITL["Human In The Loop"]
        Dashboard[React Dashboard]
        Dashboard --> ReviewQ
        Dashboard -->|Approve| QBank[(Question Bank)]
    end

    subgraph Monitoring["Observability"]
        Prometheus[Prometheus]
        Grafana[Grafana]
    end

    BEApi --> Prometheus
    DocWorker --> Prometheus
    QGenWorker --> Prometheus
```

> **Vê hình ảnh**: Nếu câu hỏi cần tham chiếu đên hình ảnh (VD: sinh câu hỏi từ biểu đồ, ảnh minh họa trong tài liệu), QGen Worker sẽ gọi **Image Search Service** (xem docs riêng: `image-search.md`) để retrieve ảnh liên quan và đưa vào context cho Generator Agent.

---

## 6. Công nghệ đề xuất

| Component | Cong nghe |
|---|---|
| **Backend** | BE Nest (Node.js/NestJS) |
| **Document Parsing** | LlamaParse / MinerU |
| **Semantic Chunking** | LangChain Recursive + Semantic |
| **Contextual Prep** | Anthropic pattern |
| **Graph RAG Engine** | LightRAG |
| **Vector Store** | PostgreSQL + pgvector |
| **Graph Store** | Neo4j |
| **Event Bus** | Redis Stream |
| **LLM** | Gemini 2.0 Flash (free/paid) |
| **Orchestration** | LangGraph |
| **Database** | PostgreSQL |
| **Human Review UI** | Custom React / Label Studio |
| **Monitoring** | Prometheus + Grafana |

---

## 7. Lộ trình implement

| Phase | Noi dung | Thoi gian |
|---|---|---|
| **1. Migrate Qdrant → pgvector** | Thêm pgvector extension, migrate data, xóa Qdrant | 2-3 ngay |
| **2. Redis Stream setup** | Define events, consumer groups | 1 ngay |
| **3. Document Ingest Worker** | Subscribe doc:uploaded, parse + embed + LightRAG | 2-3 ngay |
| **4. Hybrid Retrieval** | Kết hợp LightRAG query + pgvector + Neo4j | 1-2 ngay |
| **5. Generator + Validator** | Gemini-based generate + validate loop | 2-3 ngay |
| **6. HITL Dashboard** | Human review queue, approve/edit/reject | 2-3 ngay |
| **7. Enterprise Hardening** | Multi-tenant, monitoring | 1-2 tuan |

---

## 8. Chi phí vận hành hàng tháng

| Item | Before (Qdrant) | After (pgvector) |
|---|---|---|
| Vector DB | $0 (self-host Qdrant) + RAM | $0 (PostgreSQL da co) |
| Event Bus | RabbitMQ (self-host) | Redis Stream (co the dung Redis co san) |
| LLM (QGen) | $10-50 (GPT-4o) | $0-5 (Gemini Flash) |
| Infra services | PostgreSQL + Qdrant + Neo4j + RabbitMQ | PostgreSQL + Neo4j + Redis |
| **Tong** | **$10-50+/thang** | **$0-5/thang** |
