import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.export import router as export_router
from app.api.parse import router as parse_router
from app.api.search import router as search_router
from app.api.upload import router as upload_router

app = FastAPI(title="ParseAnything", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])
for r in (upload_router, parse_router, export_router, search_router):
    app.include_router(r, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
