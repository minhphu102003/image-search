# Kiến trúc Text-to-Speech Service — Auto-generate Audio cho Câu hỏi

> **Nguyên tắc**: Event-driven, auto-generate audio khi câu hỏi được tạo (manual hoặc AI).
> Audio được lưu cache, serve tĩnh — không generate lại mỗi lần play.

## 1. Tổng quan — Event-Driven

```mermaid
flowchart TB
    subgraph Triggers["TRIGGER POINTS"]
        M[Manual: User nhập text + tạo câu hỏi] --> RS
        A[QGen Worker: AI generate câu hỏi xong] --> RS
        E[User edit text câu hỏi] --> RS
    end

    subgraph Stream["REDIS STREAM"]
        RS[("question:audio:generate")]
    end

    subgraph Worker["TTS WORKER"]
        RS -->|subscribe| W[TTS Consumer Group]
        W --> S{Strategy}
        S -->|default| G[Google Cloud TTS]
        S -->|optional| GM[Gemini 2.5 Flash TTS]
        S -->|self-host| X[XTTS v2 local]
        G --> F[Save MP3 file]
        GM --> F
        X --> F
    end

    subgraph Storage["STORAGE"]
        F --> FS[(File Storage / S3)]
        F --> DB[(PostgreSQL: question_audios)]
    end

    subgraph Serve["SERVE"]
        DB --> U[Return audio URL]
        U --> PL[Browser player play audio]
    end
```

### Redis Stream Events

| Event | Producer | Consumer | Payload |
|---|---|---|---|
| `question:audio:generate` | BE Nest (manual) / QGen Worker | TTS Worker | `{ question_id, text, voice_id, speed, language }` |
| `question:audio:regenerate` | BE Nest (khi edit text) | TTS Worker | `{ question_id, text, voice_id, speed, language }` |

---

## 2. Trigger Points — 3 cách kích hoạt

```mermaid
sequenceDiagram
    participant User as User
    participant BE as BE Nest
    participant RS as Redis Stream
    participant TTS as TTS Worker
    participant FS as File Storage

    Note over User,FS: === 1. MANUAL: User nhập text + tạo câu hỏi ===
    User->>BE: Nhập text, chọn giọng, submit
    BE->>BE: Save question draft
    BE->>RS: XADD question:audio:generate
    BE-->>User: 202 Accepted
    RS-->>TTS: Consume event
    TTS->>TTS: TTS generate audio
    TTS->>FS: Save MP3
    TTS->>BE: Update question status: completed + audio URL
    User->>BE: Play câu hỏi
    BE-->>User: Serve static audio file

    Note over User,FS: === 2. QGEN AUTO: Worker tạo câu hỏi xong ===
    QGenWorker->>RS: XADD question:audio:generate { question_id, text }
    RS-->>TTS: Consume event
    TTS->>TTS: TTS generate audio
    TTS->>FS: Save MP3
    TTS->>BE: Update question status: completed + audio URL

    Note over User,FS: === 3. EDIT: User sửa text câu hỏi ===
    User->>BE: Sửa text + save
    BE->>RS: XADD question:audio:regenerate
    RS-->>TTS: Consume event
    TTS->>TTS: TTS generate audio mới
    TTS->>FS: Replace MP3 file (hoặc xoá cũ + tạo mới)
    TTS->>BE: Update audio URL
```

---

## 3. TTS Worker — Strategy Pattern

```mermaid
flowchart TB
    subgraph Input["Input"]
        I["question_id, text, voice_id, speed"]
    end

    subgraph Router["Router"]
        I --> C{Config: TTS.Provider}
        C -->|google-tts| G[GoogleCloudTTSStrategy]
        C -->|gemini-tts| GM[GeminiTTSStrategy]
        C -->|xtts-v2| X[XTTSv2Strategy]
    end

    subgraph Execute["Execute"]
        G --> G1[Call Google Cloud TTS API]
        GM --> GM1[Call Gemini 2.5 Flash TTS API]
        X --> X1[Load model + inference local]

        G1 --> A[Return audio bytes]
        GM1 --> A
        X1 --> A
    end

    subgraph PostProcess["Post Process"]
        A --> P1[Convert to MP3 128kbps]
        P1 --> P2[Generate filename: question_id + timestamp + .mp3]
        P2 --> P3[Save to file storage]
        P3 --> P4[Save metadata to DB: question_audios]
        P4 --> P5[Update question status: COMPLETED + audio_url]
    end
```

### Code concept — Strategy selection

```text
Cấu hình:
{
  "TTS": {
    "Provider": "google-tts",       // google-tts | gemini-tts | xtts-v2
    "GoogleCloud": {
      "Voice": "vi-VN-Wavenet-A",   // Female
      "Language": "vi-VN",
      "Speed": 1.0,
      "SampleRate": 24000
    },
    "Gemini": {
      "Voice": "Kore",              // 30 HD voices
      "Language": "vi-VN",
      "Temperature": 0.4
    },
    "XttsV2": {
      "ModelPath": "./models/xtts-v2",
      "SpeakerWav": "./voices/teacher1.wav",
      "Device": "cuda"
    }
  }
}
```

---

## 4. Audio Lifecycle — Question Status

```mermaid
flowchart LR
    D[DRAFT] -->|user submit| PA[PENDING_AUDIO]
    PA -->|TTS done + file saved| C[COMPLETED]
    C -->|user edit text| PA
    PA -->|TTS failed| F[FAILED]
    F -->|retry| PA

    D -->|delete| X((Xoá))
    PA -->|delete| X
    C -->|delete| X
    X -->|cleanup audio file| CL[Clean File]
```

### Status transitions:

| Status | Ý nghĩa | Audio URL |
|---|---|---|
| `DRAFT` | User đang soạn, chưa submit | null |
| `PENDING_AUDIO` | Đã submit, chờ TTS worker | null |
| `COMPLETED` | TTS xong, có audio | ✅ URL |
| `FAILED` | TTS lỗi | null |
| Edit text | Về lại `PENDING_AUDIO`, URL cũ invalid | null |

---

## 5. Audio Caching Decision

| Tiêu chí | Lưu cache | Không lưu (generate mỗi lần) |
|---|---|---|
| **Chi phí TTS** | ✅ Chỉ tốn 1 lần | ❌ Tốn N lần (N học sinh × M lần nghe) |
| **Tốc độ play** | ✅ Instant (serve file) | ❌ ~1-3s chờ mỗi lần |
| **Consistency** | ✅ Cùng text = cùng giọng | ❌ Có thể khác nhau |
| **Edit text** | ❌ Phải regen + cleanup | ✅ Tự động fix |
| **Storage** | ~50-100KB/câu = 1GB/10K câu | $0 |

**Phân tích storage:**
- 100,000 câu hỏi × 80KB ≈ **8GB** — không đáng kể so với lợi ích
- Xoá question → cleanup audio tương ứng

**Quyết định: LƯU CACHE. Trả về static file URL (không streaming).**

---

## 6. Sequence — Xuyên suốt

```mermaid
sequenceDiagram
    participant User as User
    participant BE as BE Nest
    participant RS as Redis Stream
    participant TTS as TTS Worker
    participant FS as File Storage
    participant DB as PostgreSQL
    participant Player as Browser Audio Player

    Note over User,Player: === CREATE: Manual question with audio ===
    User->>BE: Text + voice config + submit
    BE->>DB: INSERT question status=DRAFT
    BE-->>User: Show form

    User->>BE: Confirm create
    BE->>DB: UPDATE status=PENDING_AUDIO
    BE->>RS: XADD question:audio:generate
    BE-->>User: 202 - generating audio...

    RS-->>TTS: Consume event
    TTS->>TTS: Select TTS strategy
    TTS->>TTS: Generate audio bytes
    TTS->>FS: Save MP3 file
    FS-->>TTS: file_path
    TTS->>DB: INSERT question_audios { question_id, file_path, duration, voice_id }
    TTS->>BE: emit question:audio:completed { question_id, audio_url }

    BE->>DB: UPDATE status=COMPLETED, audio_url
    BE-->>User: Audio ready notification

    User->>BE: Click play
    BE->>FS: Serve static MP3 file
    FS-->>Player: Audio stream
```

---

## 7. Voice Management

### 7a. Voice options per provider

| Provider | Voices | Tiếng Việt | Giá |
|---|---|---|---|
| **Google Cloud TTS** | 8 voices (4 nữ, 4 nam), Standard/WaveNet/Neural2 | ✅ | $0 (free 1M chars/tháng) |
| **Gemini 2.5 Flash TTS** | 30 HD voices, natural-language steering | ❓ Cần verify | $0.30/1M input + $2.50/1M output |
| **XTTS v2** (self-host) | Clone unlimited voices từ 6s audio | ✅ (fine-tune) | $0 (cần GPU 4GB+ VRAM) |

### 7b. Teacher-voice mapping

```text
Bảng teachers:
  - teacher_id
  - default_voice: "vi-VN-Wavenet-A"
  - tts_provider: "google-tts"

Khi tạo câu hỏi:
  User chọn giọng (nếu muốn) → lưu vào question_audios.voice_id
  Nếu không chọn → dùng default_voice của teacher
```

---

## 8. Kiến trúc Deployment

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        Web[Web App] --> BEApi[BE Nest API]
    end

    subgraph BE["BE NEST"]
        BEApi --> Pg[(PostgreSQL)]
        BEApi --> RS[("Redis Stream")]
    end

    subgraph Worker["TTS WORKER"]
        RS -->|question:audio:generate| TTSWorker[TTS Worker]
        TTSWorker -->|strategy| GCloud[Google Cloud TTS API]
        TTSWorker -->|strategy| Gemini[Gemini 2.5 TTS API]
        TTSWorker -->|strategy| XTTS[XTTS v2 local - GPU optional]
        TTSWorker --> FS[(File Storage / S3)]
        TTSWorker --> Pg
        TTSWorker --> BE
    end

    subgraph Serve["AUDIO SERVE"]
        BEApi --> FS
        Web --> FS
    end

    subgraph Integration["TICH HOP"]
        QGenWorker[QGen Worker] --> RS
    end

    subgraph Monitoring["Observability"]
        Prometheus[Prometheus]
        Grafana[Grafana]
    end

    BEApi --> Prometheus
    TTSWorker --> Prometheus
```

---

## 9. Công nghệ

| Component | Cong nghe | Cost |
|---|---|---|
| **TTS Provider (default)** | Google Cloud Text-to-Speech (WaveNet) | $0 (free 1M chars/tháng) |
| **TTS Provider (optional)** | Gemini 2.5 Flash TTS | $0.30/1M input tokens |
| **TTS Provider (self-host)** | XTTS v2 (Coqui) | $0 + GPU 4GB VRAM |
| **Event Bus** | Redis Stream | $0 (da co) |
| **File Storage** | Local / S3 / Cloud Storage | $0 - $rẻ |
| **Database** | PostgreSQL | $0 (da co) |
| **Audio Format** | MP3 128kbps | - |

---

## 10. Chi phí ước tính

| Scenario | Tháng | Google Cloud TTS | Ghi chú |
|---|---|---|---|
| MVP (1K câu hỏi/tháng, ~100 chars/câu) | 100K chars | **$0** | Trong free tier (1M chars) |
| Medium (10K câu/tháng, ~200 chars/câu) | 2M chars | **$4** | Vượt free tier 1M, dùng Standard $4/1M |
| Scale (100K câu/tháng, ~200 chars/câu) | 20M chars | **$64** | Standard $4/1M |
| Scale + XTTS v2 (100K câu/tháng) | Unlimited | **$0** | Chỉ tốn GPU điện |

---

## 11. Lộ trình implement

| Phase | Noi dung | Thoi gian |
|---|---|---|
| **1. Redis Stream events** | Define events, consumer group | 1 ngay |
| **2. Google Cloud TTS strategy** | API integration, save file, update DB | 2 ngay |
| **3. Trigger integration** | Manual create + QGen auto emit event | 1-2 ngay |
| **4. Audio serve + cache** | Static file URL, CDN, cleanup | 1 ngay |
| **5. Voice management** | Teacher default voice, voice selector UI | 1 ngay |
| **6. XTTS v2 strategy** | Self-host fallback, GPU inference | 2-3 ngay |
| **7. Gemini TTS strategy** | Optional upgrade, verify tiếng Việt | 1 ngay |
