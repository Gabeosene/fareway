from fastapi import FastAPI, HTTPException, Body
from typing import List, Optional
from pydantic import BaseModel
import manager

app = FastAPI(title="Congestion Control API")

# --- Schemas ---

class Observation(BaseModel):
    link_id: str
    flow: int

class QuoteRequest(BaseModel):
    user_id: str
    origin: str  # Ignored for single-link demo simplifiction
    dest: str    # Ignored

class ReserveRequest(BaseModel):
    quote_id: str

class ConfirmRequest(BaseModel):
    reservation_id: str

# --- Dependency ---
mgr = manager.get_manager()

# --- Endpoints ---

@app.post("/observations")
def ingest_observation(obs: Observation):
    """Update Twin state (Simulation/Sensor input)."""
    mgr.twin.ingest_observation(obs.link_id, obs.flow)
    return {"status": "ok"}

@app.get("/network/status")
def get_network_status():
    """View current Twin state."""
    # Run a tick on read to ensure fresh derived data? 
    # No, tick should be separate, but for simple API pull we can just returned state.
    links = []
    for l in mgr.twin.links.values():
        links.append({
            "id": l.id,
            "ci": round(l.current_ci, 2),
            "forecast": round(l.forecast_ci, 2),
            "current_price": l.current_price,
            "status": "CONGESTED" if l.current_ci > 0.8 else "FLOWING"
        })
    return {"links": links}

@app.post("/quotes")
def get_quotes(req: QuoteRequest):
    """Get travel options."""
    # For this demo, we return quotes for ALL links to show comparison
    # In reality, this would run a pathfinding algo
    quotes = []
    for link_id in mgr.twin.links.keys():
        q = mgr.service.create_quote(req.user_id, link_id)
        quotes.append(q)
    return {"quotes": quotes}

@app.post("/reserve")
def reserve(req: ReserveRequest):
    try:
        res = mgr.service.reserve(req.quote_id)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/confirm")
def confirm(req: ConfirmRequest):
    try:
        receipt = mgr.service.confirm(req.reservation_id)
        return receipt
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/step")
def manual_tick():
    """Force a simulation tick (for manual demo pacing)."""
    mgr.twin.tick()
    return {"status": "ticked"}

@app.get("/users/{user_id}")
def get_user_balance(user_id: str):
    u = mgr.twin.users.get(user_id)
    if not u:
        raise HTTPException(404)
    return u
