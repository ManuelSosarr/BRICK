from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.routes_upload import router as upload_router
from app.routes_dashboard import router as dashboard_router
from app.routes_export import router as export_router
from app.routes_vici import router as vici_router
from app.routes_skiptrace import router as skiptrace_router
from app.routes_agent import router as agent_router
from app.routes_burner import router as burner_router
from app.routes_admin import router as admin_router
from app.scheduler import start_scheduler, stop_scheduler

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="BRICK API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "message": "BRICK API running"}

app.include_router(upload_router,    prefix="/api/upload",    tags=["upload"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(export_router,    prefix="/api/export",    tags=["export"])
app.include_router(vici_router,      prefix="/api/vici",      tags=["vici"])
app.include_router(skiptrace_router, prefix="/api/skiptrace", tags=["skiptrace"])
app.include_router(agent_router,     prefix="/api/agent",     tags=["agent"])
app.include_router(burner_router,    prefix="/api/burner",    tags=["burner"])
app.include_router(admin_router,     prefix="/api/admin",     tags=["admin"])
