# Beekid AI Platform — Data & Event Flow Xuyên suốt Hệ thống

> Tài liệu này mô tả toàn bộ luồng dữ liệu và event giữa các module.
> Kết hợp thông tin từ 3 tài liệu kiến trúc con.

---

## 1. Tất cả Redis Stream Events

| # | Event | Producer | Consumer | Payload | Module gốc |
|---|---|---|---|---|---|
| 1 | `doc:uploaded` | BE Nest | Document Ingest Worker | `{ doc_id, file_path, user_id }` | QGen |
| 2 | `doc:ingested` | Document Ingest Worker | BE Nest | `{ doc_id, status: "ready" }` | QGen |
| 3 | `question:generate` | BE Nest | Question Gen Worker | `{ doc_id, params, request_id }` | QGen |
| 4 | `question:generated` | Question Gen Worker | BE Nest | `{ request_id, questions[] }` | QGen |
| 5 | `image:uploaded` | BE Nest | Image Ingest Worker | `{ image_id, file_path, user_id }` | Image Search |
| 6 | `image:indexed` | Image Ingest Worker | BE Nest | `{ image_id, status: "indexed" }` | Image Search |
| 7 | `image:search` | QGen Worker | Image Search Service | `{ query, top_k }` | Image Search |
| 8 | `question:audio:generate` | BE Nest / QGen Worker | TTS Worker | `{ question_id, text, voice_id, speed, language }` | TTS |
| 9 | `question:audio:regenerate` | BE Nest | TTS Worker | `{ question_id, text, voice_id, speed, language }` | TTS |

---

## 2. Event Chains

### 2a. Document → Question → Audio

```mermaid
sequenceDiagram
    participant User as User
    participant BE as BE Nest
    participant RS as Redis Stream
    participant Ingest as Document Ingest
    participant QGen as QGen Worker
    participant Image as Image Search
    participant TTS as TTS Worker

    Note over User,TTS: === INGEST ===
    User->>BE: Upload file
    BE->>RS: 1. doc:uploaded
    RS-->>Ingest: consume
    Ingest->>Ingest: Parse + chunk + graph + embed
    Ingest->>RS: 2. doc:ingested
    RS-->>BE: consume

    Note over User,TTS: === QGEN ===
    User->>BE: Generate questions
    BE->>RS: 3. question:generate
    RS-->>QGen: consume

    alt Có hình ảnh liên quan
        QGen->>RS: 7. image:search
        RS-->>Image: consume
        Image-->>QGen: Return Top-K images
    end

    QGen->>QGen: Generator + Validator (loop)
    QGen->>RS: 4. question:generated
    RS-->>BE: consume
    BE->>User: Questions ready for review

    Note over User,TTS: === TTS AUTO ===
    QGen->>RS: 8. question:audio:generate
    RS-->>TTS: consume
    TTS->>TTS: TTS generate audio
    TTS->>BE: Update question audio URL
    TTS->>RS: Done (no event needed)
```

### 2b. Image Ingest độc lập

```mermaid
sequenceDiagram
    participant User as User
    participant BE as BE Nest
    participant RS as Redis Stream
    participant Img as Image Ingest Worker

    User->>BE: Upload image
    BE->>RS: 5. image:uploaded
    RS-->>Img: consume
    Img->>Img: CLIP/SigLIP embed + (opt) Gemini caption
    Img->>RS: 6. image:indexed
    RS-->>BE: consume
    BE->>User: Image indexed
```

### 2c. TTS Manual — Audio khi user tạo câu hỏi thủ công

```mermaid
sequenceDiagram
    participant User as User
    participant BE as BE Nest
    participant RS as Redis Stream
    participant TTS as TTS Worker

    User->>BE: Tạo câu hỏi + nhập text + chọn giọng
    BE->>BE: Save question DRAFT
    User->>BE: Confirm create
    BE->>RS: 8. question:audio:generate
    BE-->>User: 202 Accepted
    RS-->>TTS: consume
    TTS->>TTS: TTS generate audio
    TTS->>BE: Audio ready
    BE-->>User: Audio URL
```

### 2d. Edit text → Regenerate audio

```mermaid
sequenceDiagram
    participant User as User
    participant BE as BE Nest
    participant RS as Redis Stream
    participant TTS as TTS Worker

    User->>BE: Sửa text câu hỏi
    BE->>BE: Update text, invalidate old audio URL
    BE->>RS: 9. question:audio:regenerate
    RS-->>TTS: consume
    TTS->>TTS: Generate audio mới
    TTS->>BE: New audio URL
    BE-->>User: Audio updated
```

---

## 3. Data Lifecycle

### 3a. Document Lifecycle

```mermaid
stateDiagram-v2
    [*] --> UPLOADING: User upload file
    UPLOADING --> PROCESSING: "doc uploaded"
    PROCESSING --> PARSING: Worker receive
    PARSING --> CHUNKING: LlamaParse done
    CHUNKING --> INDEXING: Semantic chunks ready
    INDEXING --> READY: "Embed + graph done → doc ingested"

    PARSING --> FAILED: Parse error
    CHUNKING --> FAILED: Chunk error
    INDEXING --> FAILED: Embed error

    FAILED --> RETRY: Manual retry
    RETRY --> PROCESSING

    READY --> [*]
```

### 3b. Question Lifecycle

```mermaid
stateDiagram-v2
    [*] --> GENERATING: "question generate"
    GENERATING --> DRAFT: Generator done
    DRAFT --> VALIDATING: Validator score < threshold
    VALIDATING --> DRAFT: Retry (max 3)
    DRAFT --> PENDING_REVIEW: Validator score >= threshold
    PENDING_REVIEW --> APPROVED: Human approve
    PENDING_REVIEW --> REJECTED: Human reject
    PENDING_REVIEW --> REGENERATING: Human edit → regenerate
    REGENERATING --> DRAFT

    APPROVED --> QUEUED_AUDIO: Auto trigger TTS
    QUEUED_AUDIO --> AUDIO_READY: TTS done
    AUDIO_READY --> [*]

    REJECTED --> [*]
```

### 3c. Audio Lifecycle

```mermaid
stateDiagram-v2
    [*] --> PENDING: "question audio generate"
    PENDING --> GENERATING: TTS worker receive
    GENERATING --> COMPLETED: TTS success, save file
    GENERATING --> FAILED: TTS error

    COMPLETED --> REGENERATING: "User edit text → question audio regenerate"
    REGENERATING --> GENERATING

    FAILED --> PENDING: Retry

    COMPLETED --> [*]
```

---

## 4. Consumer Groups — Redis Stream

| Stream | Consumer Group | Consumers | Ghi chú |
|---|---|---|---|
| `doc:uploaded` | `doc-ingest` | Document Ingest Worker | 1 consumer (có thể scale) |
| `question:generate` | `qgen` | Question Gen Worker | 1 consumer |
| `image:uploaded` | `img-ingest` | Image Ingest Worker | 1 consumer |
| `image:search` | `img-search` | Image Search Service | Có thể nhiều workers |
| `question:audio:generate` | `tts` | TTS Worker | 1 consumer |
| `question:audio:regenerate` | `tts` | TTS Worker | Cùng group với generate |

---

## 5. Tổng quan Event Flow

```mermaid
flowchart LR
    subgraph BE["BE NEST"]
        BE_API[BE API]
    end

    subgraph Stream["REDIS STREAM"]
        direction TB
        S1[(doc:uploaded)]
        S2[(doc:ingested)]
        S3[(question:generate)]
        S4[(question:generated)]
        S5[(image:uploaded)]
        S6[(image:indexed)]
        S7[(image:search)]
        S8[(question:audio:generate)]
        S9[(question:audio:regenerate)]
    end

    subgraph Workers["WORKERS"]
        IW[Document Ingest Worker]
        QW[Question Gen Worker]
        IImg[Image Ingest Worker]
        IS[Image Search]
        TW[TTS Worker]
    end

    BE_API -->|upload| S1
    BE_API -->|generate question| S3
    BE_API -->|upload image| S5
    BE_API -->|manual TTS| S8

    S1 --> IW
    IW --> S2
    S2 --> BE_API

    S3 --> QW
    QW --> S4
    QW -->|có image context| S7
    QW -->|auto audio| S8

    S7 --> IS

    S5 --> IImg
    IImg --> S6
    S6 --> BE_API

    S8 --> TW
    S9 --> TW

    BE_API -->|edit text| S9
```

---

## 6. File kiến trúc liên quan

| File | Nội dung |
|---|---|
| [`system-overview.md`](./system-overview.md) | Tổng quan kiến trúc toàn hệ thống |
| [`rag-hybrid-question-generation.md`](./rag-hybrid-question-generation.md) | Chi tiết Document Ingest + Question Generation + HITL |
| [`image-search.md`](./image-search.md) | Chi tiết Image Search (3 approaches) |
| [`text-to-speech.md`](./text-to-speech.md) | Chi tiết TTS (event-driven, strategy pattern) |
