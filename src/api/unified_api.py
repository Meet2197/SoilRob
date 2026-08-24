from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="SoilRob Thermal+LiDAR Fusion API", version="1.0")

engine = None  # injected by main.py


class ThermalReading(BaseModel):
    temp_f: Optional[float] = None
    timestamp_utc: Optional[float] = None


class LidarReading(BaseModel):
    Modus: Optional[int] = None
    Oeffnungswinkel: Optional[int] = None
    Fehlercode_Sensor: Optional[int] = None
    Warnungscode_Sensor: Optional[int] = None
    timestamp_utc: Optional[float] = None


@app.post("/ingest/thermal/{site_id}")
def ingest_thermal(site_id: str, reading: ThermalReading):
    engine.add_thermal(site_id, reading.dict())
    return {"status": "ok"}


@app.post("/ingest/lidar/{site_id}")
def ingest_lidar(site_id: str, reading: LidarReading):
    engine.add_lidar(site_id, reading.dict())
    return {"status": "ok"}


@app.get("/fused/latest")
def fused_latest():
    return engine.latest() or {}


@app.get("/fused/history")
def fused_history(n: int = 100):
    return engine.history(n)


@app.get("/qa/summary")
def qa_summary(n: int = 50):
    return engine.qa_summary(n)


@app.get("/health")
def health():
    return {"status": "running"}