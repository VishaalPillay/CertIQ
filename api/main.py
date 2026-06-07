# api/main.py
import asyncio
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.dependencies import get_orchestrator, get_fabric_iq, append_trace
from api.routes import learner, assessment, manager, telemetry
from api.models.responses import HealthResponse
from reasoning.trace_hook import register_trace_callback

logger = logging.getLogger(__name__)

# Global reference to the main thread's event loop for thread-safe scheduling
main_loop = None

def sync_trace_callback(step_info: dict):
    """Bridge synchronous agent trace triggers to the async WebSocket loop."""
    global main_loop
    if main_loop and main_loop.is_running():
        main_loop.call_soon_threadsafe(
            lambda: asyncio.create_task(broadcast_trace_step(step_info))
        )

# ── Lifespan: warm singletons and register hooks at startup ────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()
    
    # Warm up orchestrator (which initializes lazy specialist agents) and ontology
    get_orchestrator()
    get_fabric_iq()
    
    # Register the trace callback hook
    register_trace_callback(sync_trace_callback)
    
    print("[CertIQ] All singletons warmed. API ready.")
    yield
    print("[CertIQ] Shutting down.")

app = FastAPI(
    title="CertIQ API",
    description="Multi-agent enterprise certification intelligence platform",
    version="1.0.0",
    lifespan=lifespan
)

# ── CORS ─────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",    # Vite dev server
        "http://localhost:4173",    # Vite preview
        "https://certiq-frontend.azurestaticapps.net"  # Production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────
app.include_router(learner.router,    prefix="/api/v1")
app.include_router(assessment.router, prefix="/api/v1")
app.include_router(manager.router,    prefix="/api/v1")
app.include_router(telemetry.router,  prefix="/api/v1")

# ── Health Endpoint ───────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", agents=7, knowledge_chunks=62, version="1.0.0")

# ── Global Exception Handler ──────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    # Map GitHub Models rate limit to 503
    exc_str = str(exc).lower()
    if "429" in exc_str or "rate limit" in exc_str:
        return JSONResponse(status_code=503, content={
            "error": "service_busy",
            "detail": "AI service rate limited. Please retry in 5 seconds.",
            "retry_after": 5
        })
    return JSONResponse(status_code=500, content={
        "error": "internal_error",
        "detail": str(exc)
    })

# ── WebSocket: Real-Time Reasoning Trace Stream ───────────────────
active_connections: list[WebSocket] = []

@app.websocket("/ws/trace")
async def websocket_trace(websocket: WebSocket):
    """
    Frontend connects here to receive live reasoning trace steps.
    Implements 15-second keepalive ping to prevent connection drops.
    """
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await asyncio.sleep(15)
            await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)
    except Exception:
        if websocket in active_connections:
            active_connections.remove(websocket)

async def broadcast_trace_step(step: dict):
    """Broadcast trace steps to all connected WebSocket clients and store in trace log."""
    append_trace(step)
    for conn in list(active_connections):
        try:
            await conn.send_json(step)
        except Exception:
            if conn in active_connections:
                active_connections.remove(conn)
