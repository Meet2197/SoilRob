from typing import Any

from fastapi import FastAPI, HTTPException, Query

from src.fusion.fusion_engine import FusionEngine


# ============================================================
# FastAPI application
# ============================================================

app = FastAPI(
    title="SoilRob Fusion API",
    description="Multi-sensor soil data fusion and quality-assurance API",
    version="1.0.0",
)


# ============================================================
# Shared FusionEngine instance
# ============================================================

# Injected by main.py:
#
#     unified_api.engine = engine
#
engine: FusionEngine | None = None


# ============================================================
# Helper functions
# ============================================================

def get_engine() -> FusionEngine:
    """
    Return the active FusionEngine.

    Raises HTTP 503 if the application has not been
    initialized by main.py yet.
    """

    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="FusionEngine is not initialized",
        )

    return engine


def json_safe(value: Any) -> Any:
    """
    Convert common pandas / NumPy values into JSON-safe values.
    """

    if value is None:
        return None

    # pandas / NumPy scalar values
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass

    # dictionaries
    if isinstance(value, dict):
        return {
            str(key): json_safe(val)
            for key, val in value.items()
        }

    # lists / tuples
    if isinstance(value, (list, tuple)):
        return [
            json_safe(item)
            for item in value
        ]

    return value


# ============================================================
# Root
# ============================================================

@app.get("/")
def root():
    """
    Basic API information.
    """

    return {
        "name": "SoilRob Fusion API",
        "version": app.version,
        "status": "running",
        "engine_initialized": engine is not None,
    }


# ============================================================
# Health
# ============================================================

@app.get("/health")
def health():
    """
    Application health status.
    """

    active_engine = engine is not None

    return {
        "status": "ok" if active_engine else "degraded",
        "engine_initialized": active_engine,
    }


# ============================================================
# Latest fused record
# ============================================================

@app.get("/latest")
def latest():
    """
    Return the most recent QA-approved fused record.
    """

    active_engine = get_engine()

    record = active_engine.latest()

    if record is None:
        return {
            "status": "no_data",
            "record": None,
        }

    return {
        "status": "ok",
        "record": json_safe(record),
    }


# ============================================================
# Fusion history
# ============================================================

@app.get("/history")
def history(
    n: int = Query(
        default=100,
        ge=1,
        le=10000,
        description="Number of recent fused records to return",
    )
):
    """
    Return recent QA-approved fused records.
    """

    active_engine = get_engine()

    records = active_engine.history(n)

    return {
        "status": "ok",
        "count": len(records),
        "records": json_safe(records),
    }


# ============================================================
# QA reports
# ============================================================

@app.get("/qa")
def qa_summary(
    n: int = Query(
        default=50,
        ge=1,
        le=10000,
        description="Number of recent QA reports to return",
    )
):
    """
    Return recent quality-assurance reports.
    """

    active_engine = get_engine()

    reports = active_engine.qa_summary(n)

    return {
        "status": "ok",
        "count": len(reports),
        "reports": json_safe(reports),
    }


# ============================================================
# API status / statistics
# ============================================================

@app.get("/status")
def status():
    """
    Return a compact operational status of the fusion system.
    """

    active_engine = get_engine()

    latest_record = active_engine.latest()
    history_records = active_engine.history(1)
    qa_reports = active_engine.qa_summary(1)

    return {
        "status": "running",
        "engine_initialized": True,
        "has_fused_data": latest_record is not None,
        "fused_record_count": len(
            active_engine.fused_buffer
        ),
        "quarantine_record_count": len(
            active_engine.quarantine_buffer
        ),
        "qa_report_count": len(
            active_engine.qa_reports
        ),
        "latest_timestamp": (
            latest_record.get("timestamp_utc")
            if latest_record
            else None
        ),
        "latest_qa_report": (
            json_safe(qa_reports[-1])
            if qa_reports
            else None
        ),
    }


# ============================================================
# Quarantine records
# ============================================================

@app.get("/quarantine")
def quarantine(
    n: int = Query(
        default=50,
        ge=1,
        le=10000,
        description="Number of recent quarantined records to return",
    )
):
    """
    Return records that failed QA validation.
    """

    active_engine = get_engine()

    records = list(active_engine.quarantine_buffer)[-n:]

    return {
        "status": "ok",
        "count": len(records),
        "records": json_safe(records),
    }
