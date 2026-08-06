# backend/main.py
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import sensors, data, streams
from services.mqtt_service import MQTTService
from services.influx_service import InfluxService
from services.sensor_registry import SensorRegistry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Global Services ────────────────────────────────────────────────────────
mqtt_service = MQTTService()
influx_service = InfluxService()
sensor_registry = SensorRegistry()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle"""
    logger.info("Starting sensor platform services...")
    
    # Initialize services
    await influx_service.initialize()
    await mqtt_service.start(sensor_registry)
    
    logger.info("All services started successfully")
    yield
    
    # Shutdown
    logger.info("Shutting down services...")
    await mqtt_service.stop()
    await influx_service.close()

app = FastAPI(
    title="Sensor Data Platform API",
    description="Backend for multi-sensor data ingestion and visualization",
    version="1.0.0",
    lifespan=lifespan
)

# ─── CORS Configuration ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # Next.js
        "http://localhost:8080",   # Vue.js
        "http://localhost:3001",   # Grafana
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Include Routers ─────────────────────────────────────────────────────────
app.include_router(sensors.router, prefix="/api/sensors",  tags=["sensors"])
app.include_router(data.router,    prefix="/api/data",     tags=["data"])
app.include_router(streams.router, prefix="/api/streams",  tags=["streams"])

# ─── Static Files (captured images) ─────────────────────────────────────────
app.mount("/images", StaticFiles(directory="/app/images"), name="images")

# ─── WebSocket Manager ───────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WS client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.active_connections.remove(conn)

manager = ConnectionManager()

# Register broadcast callback with MQTT service
mqtt_service.set_broadcast_callback(manager.broadcast)

@app.websocket("/ws/live")
async def websocket_live_data(websocket: WebSocket):
    """WebSocket endpoint for live sensor data streaming"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, data pushed via broadcast
            await asyncio.sleep(1)
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WS client disconnected")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "mqtt":   mqtt_service.is_connected,
        "influx": await influx_service.ping(),
        "sensors": sensor_registry.get_summary()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)