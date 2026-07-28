from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.session import init_db
from app.api.routes import router

app=FastAPI(title=settings.project_name, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.backend_cors_origins.split(',')], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

@app.on_event("startup")
def startup(): init_db()

@app.get("/health")
def health(): return {"status":"ok","project":"ReefFusion"}
