# Beekid AI Platform — Kiến trúc Hệ thống Tổng quan

> Tài liệu này mô tả toàn bộ kiến trúc Beekid AI Platform ở mức hệ thống.
> Các module chi tiết được tham chiếu ở cuối tài liệu.

## 1. System Context

```mermaid
C4Context
    Person(teacher, "Giáo viên", "Người dùng chính: soạn tài liệu, tạo câu hỏi, phê duyệt")
    Person(student, "Học sinh", "Người dùng cuối: làm bài tập, nghe audio")

    System_Boundary(boundary, "Beekid AI Platform") {
        System(be, "BE Nest API", "Backend chính, emit events, serve API")
        SystemDb(pg, "PostgreSQL + pgvector", "Dữ liệu chính + vector embeddings")
        SystemDb(neo4j, "Neo4j", "Graph entities + relationships")
        SystemQueue(redis, "Redis Stream", "Event bus bất đồng bộ")
        System(ingest, "Document Ingest Worker", "Parse + chunk + index documents")
        System(qgen, "Question Gen Worker", "Hybrid GraphRAG + LLM generate câu hỏi")
        System(imagesearch, "Image Search Service", "Text-to-Image retrieval")
        System(tts, "TTS Worker", "Text-to-Speech auto-generate audio")
        System(review, "Human Review Dashboard", "HITL: duyệt/sửa/từ chối câu hỏi")
        System(storage, "File Storage", "Lưu MP3, images, documents")
    }

    Rel(teacher, be, "Upload tài liệu, tạo câu hỏi, duyệt review")
    Rel(teacher, review, "Approve/Edit/Reject câu hỏi draft")
    Rel(student, be, "Làm bài tập, play audio câu hỏi")
    Rel(be, redis, "Emit events")
    Rel(be, pg, "CRUD")
    Rel(be, storage, "Serve files")
    Rel(ingest, redis, "Subscribe: doc:uploaded")
    Rel(ingest, pg, "Save chunks + embeddings")
    Rel(ingest, neo4j, "Save graph nodes + edges")
    Rel(qgen, redis, "Subscribe: question:generate")
    Rel(qgen, pg, "Vector search + entities + relations")
    Rel(qgen, neo4j, "Graph traversal")
    Rel(imagesearch, pg, "Vector search image embeddings")
    Rel(imagesearch, bee, "API: image search")
    Rel(tts, redis, "Subscribe: question:audio:generate")
    Rel(tts, storage, "Save audio MP3")
    Rel(tts, pg, "Update question audio status")
    Rel(qgen, imagesearch, "Lấy context ảnh cho generator")
    Rel(tts, bee, "Gọi BE callback khi audio xong")
```

> **Lưu ý**: C4Context là Mermaid mở rộng, có thể không render trên tất cả platform.
> Xem diagram tương đương ở mục 2 bên dưới.

---

## 2. Tổng quan — Các Subsystem

```mermaid
flowchart TB
    subgraph Actors["ACTORS"]
        T[Giáo viên]
        S[Học sinh]
    end

    subgraph Core["CORE SERVICE"]
        BE[BE Nest API] --> PG[(PostgreSQL + pgvector)]
        BE --> RS[(Redis Stream)]
        BE --> FS[(File Storage)]
    end

    subgraph Ingest["MODULE: Document Ingest"]
        sub_ingest[Document Ingest Worker]
        sub_ingest --> N4J[(Neo4j)]
        sub_ingest --> PG
    end

    subgraph QGen["MODULE: Question Generation"]
        sub_qgen[Question Gen Worker]
        sub_qgen -->|LightRAG| LR[LightRAG Query Engine]
        LR --> PG
        LR --> N4J
        sub_qgen -->|generate + validate| LLM[Gemini 2.0 Flash]
        sub_qgen --> RQ[(Review Queue)]
    end

    subgraph Img["MODULE: Image Search"]
        sub_img[Image Search Service]
        sub_img --> CLIP[SigLIP/CLIP local]
        sub_img --> PG
        sub_img --> LLM2[Gemini - optional]
    end

    subgraph TTSModule["MODULE: Text-to-Speech"]
        sub_tts[TTS Worker]
        sub_tts -->|strategy| GCloud[Google Cloud TTS]
        sub_tts -->|strategy| XTTS[XTTS v2 local]
        sub_tts --> FS
        sub_tts --> PG
    end

    subgraph HITL["MODULE: Human Review"]
        Dashboard[React Dashboard]
        Dashboard --> RQ
        Dashboard -->|approve| QB[(Question Bank)]
    end

    T -->|upload, create| BE
    T -->|review| Dashboard
    S -->|play audio| BE

    BE -->|doc:uploaded| sub_ingest
    BE -->|question:generate| sub_qgen
    BE -->|image:uploaded| sub_img
    BE -->|question:audio:generate| sub_tts

    sub_qgen -.->|image context| sub_img
    sub_qgen -.->|emit audio event| sub_tts

    RS -.- BE
    RS -.- sub_ingest
    RS -.- sub_qgen
    RS -.- sub_img
    RS -.- sub_tts
```

---

## 3. Shared Infrastructure

| Component | Công nghệ | Mục đích | Kiến trúc chi tiết |
|---|---|---|---|
| **PostgreSQL + pgvector** | PostgreSQL 16 + pgvector extension | Lưu tất cả dữ liệu + vector embeddings (chunks, entities, relations, images) | [`rag-hybrid-question-generation.md`](./rag-hybrid-question-generation.md), [`image-search.md`](./image-search.md) |
| **Neo4j** | Neo4j 5.x | Graph knowledge base: entities + relationships từ LightRAG | [`rag-hybrid-question-generation.md`](./rag-hybrid-question-generation.md) |
| **Redis Stream** | Redis 7.x | Event bus: emit + subscribe pattern, consumer groups | Cả 3 tài liệu |
| **File Storage** | Local / S3-compatible | Lưu tài liệu gốc, images, audio MP3 | [`text-to-speech.md`](./text-to-speech.md) |
| **Gemini API** | Gemini 2.0/2.5 Flash | LLM cho QGen (generate + validate), Image Search caption, TTS | Cả 3 tài liệu |

---

## 4. Redis Stream Event Bus

Tất cả module giao tiếp bất đồng bộ qua Redis Stream. Event flow tổng thể:

```mermaid
flowchart LR
    subgraph Events["CÁC EVENT TRÊN REDIS STREAM"]
        E1[doc:uploaded]
        E2[doc:ingested]
        E3[question:generate]
        E4[question:generated]
        E5[image:uploaded]
        E6[image:indexed]
        E7[image:search]
        E8[question:audio:generate]
        E9[question:audio:regenerate]
    end

    subgraph Producers["PRODUCERS"]
        BE[BE Nest]
        Ingest[Document Ingest Worker]
        QGen[Question Gen Worker]
        Img[Image Ingest Worker]
    end

    subgraph Consumers["CONSUMERS"]
        C_Ingest[Document Ingest Worker]
        C_QGen[Question Gen Worker]
        C_Img[Image Ingest Worker]
        C_TTS[TTS Worker]
        C_BE[BE Nest]
    end

    BE --> E1
    BE --> E3
    BE --> E5
    BE --> E8

    Ingest --> E2

    QGen --> E4
    QGen --> E7
    QGen --> E9

    Img --> E6

    E1 --> C_Ingest
    E2 --> C_BE
    E3 --> C_QGen
    E4 --> C_BE
    E5 --> C_Img
    E6 --> C_BE
    E7 --> C_Img
    E8 --> C_TTS
    E9 --> C_TTS
```

Chi tiết từng event xem tại [`data-event-flow.md`](./data-event-flow.md).

---

## 5. Module chi tiết

| Module | File kiến trúc | Chức năng chính |
|---|---|---|
| **Document Ingest + Question Generation** | [`rag-hybrid-question-generation.md`](./rag-hybrid-question-generation.md) | Parse document → chunk → LightRAG index → Hybrid Retrieval → Generator + Validator → HITL |
| **Image Search** | [`image-search.md`](./image-search.md) | 3 approaches: Pure CLIP / Hybrid Caption / Multimodal RAG, all dùng pgvector |
| **Text-to-Speech** | [`text-to-speech.md`](./text-to-speech.md) | Event-driven TTS, Strategy pattern (Google / Gemini / XTTS v2), cache + serve static |

---

## 6. Flow tổng thể: Document → Audio

```mermaid
flowchart LR
    A[Upload Document] --> B[Document Ingest: parse + chunk + graph + embed]
    B --> C[Question Generation: LightRAG + LLM + HITL]
    C --> D[(Question Bank)]
    D --> E[TTS: auto-generate audio]
    E --> F[Audio ready - student play]
    C -.->|có hình ảnh| G[Image Search: retrieve related images]
    G -.->|context ảnh| C
```

---

## 7. Công nghệ toàn hệ thống

| Layer | Công nghệ | Cost |
|---|---|---|
| **Backend** | BE Nest (NestJS) | $0 |
| **Database** | PostgreSQL + pgvector | $0 (có sẵn) |
| **Graph DB** | Neo4j 5.x | $0 (self-host) |
| **Event Bus** | Redis Stream | $0 (có sẵn) |
| **Vector Search** | pgvector | $0 (trong PostgreSQL) |
| **LLM** | Gemini 2.0/2.5 Flash | $0 (free tier) / ~$0.15/1M tokens |
| **Image Embedding** | SigLIP 2 (local) | $0 |
| **Image Caption** | Gemini 2.0 Flash | $0 (free tier) |
| **TTS (default)** | Google Cloud TTS | $0 (1M chars free/tháng) |
| **TTS (optional)** | XTTS v2 (self-host) | $0 (cần GPU) |
| **Document Parse** | LlamaParse / MinerU | $0 / $10-15/tháng |
| **File Storage** | Local / S3 | $0 - thấp |
| **Monitoring** | Prometheus + Grafana | $0 |
