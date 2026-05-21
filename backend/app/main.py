from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import reports

app = FastAPI(
    title="SOC Audit Automation",
    description="Parse SOC 1 reports and auto-fill EY Form 107-A.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
