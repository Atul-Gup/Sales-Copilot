from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import compare, health, objection, spec
from api.settings import settings

app = FastAPI(title="Showroom Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(spec.router)
app.include_router(compare.router)
app.include_router(objection.router)
