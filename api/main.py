from fastapi import FastAPI

from api.routers import health

app = FastAPI(title="Showroom Copilot")

app.include_router(health.router)
