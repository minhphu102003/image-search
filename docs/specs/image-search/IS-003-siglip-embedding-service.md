# Spec: SigLIP 2 Embedding Service

> Specification for the shared SigLIP 2 embedding service using Clean Architecture.

---

## Metadata

| Field        | Value                        |
|-------------|------------------------------|
| **ID**      | IS-003                       |
| **Title**   | SigLIP 2 Embedding Service   |
| **Phase**   | 1 — Foundation               |
| **Status**  | Draft                        |
| **Depends** | None                         |

---

## 1. Objective

Provide a unified embedding interface using SigLIP 2 (`ViT-SO400M-16-SigLIP2-384`, 1024-dim). Domain interface allows swapping models; infrastructure implementation wraps the actual SigLIP model.

---

## 2. Tech Stack

| Tool          | Purpose                    |
|--------------|----------------------------|
| torch        | Deep learning framework    |
| transformers | HuggingFace model loading  |
| Pillow       | Image processing           |

---

## 3. Detailed Design

### 3.1 Clean Architecture — AI Layer

```
src/image_search/
├── domain/
│   └── embedding_service.py   # Abstract EmbeddingService interface
├── infrastructure/
│   └── ai/
│       └── siglip_service.py  # Concrete SigLIP implementation
```

### 3.2 Domain — Abstract Interface

```python
# src/image_search/domain/embedding_service.py
from abc import ABC, abstractmethod

class EmbeddingService(ABC):
    @abstractmethod
    async def embed_image(self, image_path: str) -> list[float]:
        """Embed a single image file -> 1024-dim vector."""
        ...

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string -> 1024-dim vector."""
        ...

    @abstractmethod
    async def embed_images_batch(self, image_paths: list[str]) -> list[list[float]]:
        """Embed multiple images in one forward pass."""
        ...

    @abstractmethod
    async def embed_texts_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in one forward pass."""
        ...
```

### 3.3 Infrastructure — SigLIP Implementation

```python
# src/image_search/infrastructure/ai/siglip_service.py
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor
import structlog

from image_search.domain.embedding_service import EmbeddingService

logger = structlog.get_logger()

class SigLIPEmbeddingService(EmbeddingService):
    """Singleton SigLIP 2 embedding service."""

    def __init__(self, model_name: str = "google/siglip2-so400m-patch16-384",
                 device: str | None = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = model_name

        logger.info("loading_siglip_model", model=model_name, device=self.device)
        self.model = AutoModel.from_pretrained(model_name).to(self.device).eval()
        self.processor = AutoProcessor.from_pretrained(model_name)
        logger.info("siglip_model_loaded", model=model_name)

    async def embed_image(self, image_path: str) -> list[float]:
        image = Image.open(image_path).convert("RGB")
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model.get_image_features(**inputs)
        return outputs[0].cpu().tolist()

    async def embed_text(self, text: str) -> list[float]:
        inputs = self.processor(text=[text], return_tensors="pt", padding=True).to(self.device)
        with torch.no_grad():
            outputs = self.model.get_text_features(**inputs)
        return outputs[0].cpu().tolist()

    async def embed_images_batch(self, image_paths: list[str]) -> list[list[float]]:
        images = [Image.open(p).convert("RGB") for p in image_paths]
        inputs = self.processor(images=images, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model.get_image_features(**inputs)
        return outputs.cpu().tolist()

    async def embed_texts_batch(self, texts: list[str]) -> list[list[float]]:
        inputs = self.processor(text=texts, return_tensors="pt", padding=True).to(self.device)
        with torch.no_grad():
            outputs = self.model.get_text_features(**inputs)
        return outputs.cpu().tolist()
```

### 3.4 Model Specification

| Property       | Value                                      |
|---------------|--------------------------------------------|
| Model ID      | `google/siglip2-so400m-patch16-384`       |
| Architecture  | ViT-SO400M, patch 16, resolution 384      |
| Embedding Dim | 1024                                       |
| License       | Apache 2.0                                 |

---

## 4. Configuration

```python
# In Settings class
siglip_model: str = "google/siglip2-so400m-patch16-384"
siglip_device: str | None = None  # auto-detect
embed_batch_size: int = 8
```

| Env Var           | Default                                      | Description          |
|------------------|----------------------------------------------|----------------------|
| `IMAGE_SEARCH_SIGLIP_MODEL` | `google/siglip2-so400m-patch16-384` | HuggingFace model ID |
| `IMAGE_SEARCH_SIGLIP_DEVICE` | auto                                  | Torch device         |

---

## 5. Error Handling

| Scenario                    | Action                                    |
|----------------------------|-------------------------------------------|
| Model download fails        | Log error, fail startup                   |
| CUDA OOM                    | Fall back to CPU, log warning             |
| Invalid image file          | Raise `ValueError` with file path         |
| Empty text input            | Raise `ValueError`                        |

---

## 6. Acceptance Criteria

- [ ] `embed_image("test.jpg")` returns `list` of exactly `1024` floats
- [ ] `embed_text("a red car")` returns `list` of exactly `1024` floats
- [ ] Cosine similarity: car image + "a red car" > 0.25
- [ ] Cosine similarity: car image + "a cat" < 0.15
- [ ] Batch embedding returns correct number of vectors
- [ ] Model loads once (singleton), not per-request
- [ ] GPU → <200ms per image, CPU → <1s per image
- [ ] Domain interface can be mocked for unit tests

---

## 7. Testing Strategy

### Unit Tests
- Mock `EmbeddingService` for use case tests
- `embed_image` returns correct shape
- `embed_text` returns correct shape
- Invalid file raises `ValueError`

### Semantic Tests
- Car image + "a red car" → cosine > 0.25
- Car image + "a cat" → cosine < 0.15

### Performance Tests
- Single image latency on CPU
- Batch throughput (images/second)
