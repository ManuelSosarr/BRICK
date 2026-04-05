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

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ViciDial Analytics", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "message": "ViciDial Analytics API running"}

app.include_router(upload_router,    prefix="/api/upload",    tags=["upload"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(export_router,    prefix="/api/export",    tags=["export"])
app.include_router(vici_router,      prefix="/api/vici",      tags=["vici"])
app.include_router(skiptrace_router, prefix="/api/skiptrace", tags=["skiptrace"])
app.include_router(agent_router,     prefix="/api/agent",     tags=["agent"])
app.include_router(burner_router,    prefix="/api/burner",    tags=["burner"])
