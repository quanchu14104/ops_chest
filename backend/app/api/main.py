import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import clock
from app.api import routes_chat, routes_core, routes_proposals, routes_store
from app.config import settings
from app.jobs import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    clock.load_persisted()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Ops Chest API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(routes_core.router)
app.include_router(routes_proposals.router)
app.include_router(routes_chat.router)
app.include_router(routes_store.router)
