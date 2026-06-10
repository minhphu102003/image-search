from fastapi import FastAPI

from image_search.adapters.input.health import router as health_router
from image_search.adapters.input.rest_api import router as images_router
from image_search.adapters.input.search_router import router as search_router
from image_search.adapters.input.upload_router import router as upload_router
from image_search.infrastructure.observability.logging import configure_logging

configure_logging()

app = FastAPI(title="Image Search Service")
app.include_router(images_router)
app.include_router(search_router)
app.include_router(upload_router)
app.include_router(health_router)

try:
    from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore[import-not-found]

    Instrumentator().instrument(app).expose(app)
except ImportError:
    pass
