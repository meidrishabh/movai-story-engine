from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as api_router
from app.core.settings import settings


app = FastAPI(
    title="MovAI API",
    version="0.1.0",
)

# The UI runs as a separate app on its own port, so the browser needs CORS to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
