from fastapi import FastAPI

from image_search.adapters.input.rest_api import router as images_router
from image_search.adapters.input.search_router import router as search_router

app = FastAPI(title="Image Search Service")
app.include_router(images_router)
app.include_router(search_router)

try:
    from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore[import-not-found]

    Instrumentator().instrument(app).expose(app)
except ImportError:
    pass


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
