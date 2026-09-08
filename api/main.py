from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.logging import configure_logging
from api.routers import admin, chat, health
from api.settings import settings

configure_logging()

app = FastAPI(title="Showroom Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(admin.router)
