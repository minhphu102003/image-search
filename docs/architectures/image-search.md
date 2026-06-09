# Kiến trúc Image Search Service — Text-to-Image Retrieval

> **Nguyên tắc**: Module độc lập, event-driven. BE Nest emit event qua Redis Stream, AI workers consume.
> Có thể đứng riêng hoặc tích hợp với Question Generation.

## 1. Tổng quan - Event-Driven

```mermaid
flowchart TB
    subgraph BE["BE NEST (Backend)"]
        BE1[BE Nest API] -->|emit event| RS[(Redis Stream)]
    end

    subgraph Ingest["IMAGE INGEST WORKER"]
        RS -->|subscribe: image:uploaded| W1[Image Ingest Worker]
        W1 --> A2[CLIP/SigLIP Embed local]
        A2 --> A3[pgvector: image_embeddings]
        A3 --> A4[Optional: Gemini caption -> text embed]
        A4 --> A5[Status: INDEXED]
        A5 -->|emit image:indexed| RS
    end

    subgraph Search["IMAGE SEARCH SERVICE"]
        B1[API: search by text prompt] --> B2[CLIP/SigLIP Embed local]
        B2 --> B3{Approach}
        B3 -->|1 Pure CLIP| B4[pgvector cosine search]
        B3 -->|2 Hybrid Caption| B5[pgvector CLIP + text -> RRF]
        B3 -->|3 Multimodal RAG| B6[pgvector -> Top-5 -> Gemini]
        B4 --> B7[Return Top-K Image URLs]
        B5 --> B7
        B6 --> B8[Return Images + Answer]
    end

    subgraph Integration["TICH HOP VOI QGEN"]
        C1[QGen Worker can retrieve image context] --> B2
    end

    A3 --> Pg[(PostgreSQL + pgvector)]
    B4 --> Pg
    B5 --> Pg
    B6 --> Pg
```

### Redis Stream Events

| Event | Producer | Consumer | Payload |
|---|---|---|---|
| `image:uploaded` | BE Nest | Image Ingest Worker | `{ image_id, file_path, user_id }` |
| `image:indexed` | Image Ingest Worker | BE Nest (callback) | `{ image_id, status: "indexed" }` |
| `image:search` | QGen Worker | Image Search Service | `{ query, top_k }` |

---

## 2. Image Ingest Worker

Subscribe `image:uploaded` từ Redis Stream.

```mermaid
flowchart LR
    subgraph Event["1. Receive Event"]
        RS[(Redis Stream)] -->|image:uploaded| W[Consumer Group: img-ingest]
        W --> B[Parse payload: image_id, file_path]
    end

    subgraph Embed["2. Embed"]
        B --> C1[CLIP/SigLIP local -> embedding vector 1024d]
        C1 --> D1[Save vector -> image_embeddings table]
    end

    subgraph Optional["3. Optional: Gemini Caption"]
        D1 --> E1[Gemini 2.0 Flash -> generate caption]
        E1 --> F1[Embed caption -> text embedding model -> save to image_embeddings]
    end

    subgraph Done["4. Hoan tat"]
        F1 --> G1[Update image status: INDEXED]
        D1 --> G1
        G1 -->|emit image:indexed| RS
    end
```

---

## 3. Image Search — 3 Approaches

Config-driven: chỉ cần thay đổi `ImageSearch.Approach = 1 | 2 | 3`.

### 3a. Tổng quan 3 Approaches

```mermaid
flowchart TB
    subgraph Common["Common Steps"]
        A["Text Prompt"] --> B["CLIP/SigLIP embed local"]
        B --> C["vector(1024)"]
    end

    subgraph A1["Approach 1: Pure CLIP ($0)"]
        C --> D1["pgvector cosine search: image_embeddings WHERE model_name=siglip2-384"]
        D1 --> E1["Return Top-K: image_id + url + score"]
    end

    subgraph A2["Approach 2: Hybrid Caption ($0)"]
        C --> D2["pgvector search on CLIP embedding"]
        C --> F2["Gemini caption then text embed then pgvector search on caption"]
        D2 & F2 --> G2["RRF Fusion"]
        G2 --> E2["Return Top-K: image_id + url + score"]
    end

    subgraph A3["Approach 3: Multimodal RAG ($0)"]
        C --> D3["pgvector search top-5"]
        D3 --> H3["Top-5 images + prompt sent to Gemini 2.0 Flash vision"]
        H3 --> I3["Gemini returns natural language answer"]
        I3 --> E3["Return: Top-5 images + answer text"]
    end
```

### 3b. Sequence chi tiết

```mermaid
sequenceDiagram
    participant User as User
    participant API as ImageSearchController
    participant Clip as CLIP/SigLIP (local)
    participant Pg as PostgreSQL pgvector
    participant Gemini as Gemini API (opt)

    Note over User,Gemini: === APPROACH 1: Pure CLIP ===
    User->>API: "a red car on the beach"
    API->>Clip: embed_text("a red car on the beach")
    Clip-->>API: vector(1024)
    API->>Pg: SELECT image_id, url FROM image_embeddings<br>ORDER BY embedding <=> $1 LIMIT 10
    Pg-->>API: Top-10 results
    API-->>User: [image_urls]

    Note over User,Gemini: === APPROACH 3: Multimodal RAG ===
    User->>API: "find modern architecture buildings"
    API->>Clip: embed_text("find modern architecture buildings")
    Clip-->>API: vector
    API->>Pg: pgvector search LIMIT 5
    Pg-->>API: Top-5 image IDs + urls
    API->>Gemini: [image1..image5] + "Describe these images..."
    Gemini-->>API: "These 5 images show modern architecture..."
    API-->>User: {images, answer}
```

---

## 4. So sánh 3 Approaches

| Approach | Chi phí | Chất lượng | Độ trễ | Khi nào dùng |
|---|---|---|---|---|
| **1. Pure CLIP** | $0 | 70-85% | ~50ms | MVP, search nhanh, ít vốn |
| **2. Hybrid Caption** | ~$0.40/10K ảnh* | 80-92% | ~200ms | Cần độ chính xác cao |
| **3. Multimodal RAG** | ~$0.20/1K queries* | 85-95% | ~500ms | Cần giải thích, chat với ảnh |
| **1+3 kết hợp** | $0-$0.20/1K queries | 85-95% | ~100ms + ~400ms | Default recommend |

*Gemini 2.0 Flash paid pricing

---

## 5. Kiến trúc Deployment

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        Web[Web App] --> BEApi[BE Nest API]
    end

    subgraph Backend["BE NEST"]
        BEApi --> RS[("Redis Stream")]
        BEApi --> Pg[(PostgreSQL + pgvector)]
    end

    subgraph Worker["IMAGE INGEST WORKER"]
        RS -->|image:uploaded| ImgWorker[Image Ingest Worker]
        ImgWorker --> Clip[CLIP/SigLIP local]
        ImgWorker --> GeminiOpt[Gemini - optional]
        ImgWorker --> Pg
        ImgWorker --> RS
    end

    subgraph SearchSvc["IMAGE SEARCH SERVICE"]
        BEApi --> ImgSearch[Image Search Service]
        ImgSearch --> Clip2[CLIP/SigLIP local]
        ImgSearch --> Gemini[Gemini API - opt]
        ImgSearch --> Pg
    end

    subgraph Integration["TICH HOP"]
        QGenWorker[Question Gen Worker] --> ImgSearch
    end

    subgraph Monitoring["Observability"]
        Prometheus[Prometheus]
        Grafana[Grafana]
    end

    BEApi --> Prometheus
    ImgWorker --> Prometheus
    ImgSearch --> Prometheus
```

---

## 6. Công nghệ

| Component | Cong nghe | Cost |
|---|---|---|
| **Backend** | BE Nest (Node.js/NestJS) | $0 |
| **Image Embedding** | SigLIP 2 (local, open-source) | $0 |
| **Vector Store** | PostgreSQL + pgvector | $0 (da co) |
| **LLM Caption/Answer** | Gemini 2.0 Flash | $0 (free) hoac ~$0.00004/req |
| **Event Bus** | Redis Stream | $0 (da co hoac tu host) |
| **Database** | PostgreSQL | $0 (da co) |

### Model embedding khuyến nghị

| Model | Dim | Quality | Speed | Source |
|---|---|---|---|---|
| `clip-ViT-B-32` | 512 | 63% ImageNet | Nhanh | OpenAI |
| `clip-ViT-L-14` | 768 | 75% ImageNet | Trung binh | OpenAI |
| `ViT-SO400M-16-SigLIP2-384` | 1024 | ~82% ImageNet | Cham nhat | Google (top 1) |

---

## 7. Tích hợp với Question Generation

Khi QGen Worker cần tạo câu hỏi có tham chiếu hình ảnh (VD: biểu đồ trong slide, ảnh chụp màn hình, hình minh họa):

```text
QGen Worker nhận event question:generate từ BE Nest

    ├── [text context] LightRAG retrieval → chunks + entities
    │
    └── [image context] Gọi Image Search Service với query = nội dung liên quan
                        ──▶ Image Search trả về Top-5 ảnh + caption
                        ──▶ QGen đưa cả text + image URLs vào context của Generator
                        ──▶ Generator tạo câu hỏi (MCQ/open-ended) từ cả text và hình ảnh
```

Hoặc QGen Worker có thể emit event `image:search` qua Redis Stream để Image Search Service xử lý async.

---

## 8. Lộ trình implement

| Phase | Noi dung | Thoi gian |
|---|---|---|
| **1. Redis Stream setup** | Define events, consumer groups | 1 ngay |
| **2. Image Ingest Worker** | Subscribe image:uploaded, CLIP embed + pgvector | 2-3 ngay |
| **3. Approach 1** | Pure CLIP search, API endpoint | 1 ngay |
| **4. Approach 2** | Gemini caption -> dual search -> RRF | 2 ngay |
| **5. Approach 3** | Multimodal RAG with Gemini vision | 1-2 ngay |
| **6. Tích hợp QGen** | QGen gọi Image Search cho context | 1 ngay |
