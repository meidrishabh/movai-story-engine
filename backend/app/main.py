from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as api_router
from app.core.config import FRONTEND_DIR


app = FastAPI(
    title="MovAI API",
    version="0.1.0",
)

app.include_router(api_router)
app.mount(
    "/ui",
    StaticFiles(directory=FRONTEND_DIR, html=True),
    name="ui",
)
