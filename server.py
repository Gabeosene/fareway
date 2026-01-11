from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
# Trigger Reload
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import Optional
import time
import uvicorn
import random
import os
import threading
from collections import deque

import manager
import generator
from simulation_controller import SimulationController
from schemas import MetricType, TwinObservation

# --- Initialize System ---
# --- Initialize System ---
mgr = manager.get_manager("full_city_config.json")
gen = generator.TrafficGenerator()

# Attach agent aggressiveness to manager for state sharing
mgr.agent_aggressiveness = 1.0

# Initialize Controller
sim_controller = SimulationController(mgr, gen)
sim_controller.start()

# Analytics State
history = deque(maxlen=60)

# --- Schemas ---
class LiveLinksUpdate(BaseModel):
    link_ids: list[str] = []
    mode: Optional[str] = None

# Background History Loop
def history_updater():
    while True:
        # Capture snapshot
        link_cis = [l.current_ci for l in mgr.twin.links.values()]
        avg_ci = sum(link_cis) / len(link_cis) if link_cis else 0
        total_flow = sum([l.current_flow for l in mgr.twin.links.values()])
        sens = mgr.policy.p_config.get('price_sensitivity_factor', 5.0)
        
        history.append({
            "timestamp": time.time(),
            "avg_ci": round(avg_ci, 3),
            "total_flow": int(total_flow),
            "sensitivity": round(sens, 2)
        })
        time.sleep(0.5)

hist_thread = threading.Thread(target=history_updater, daemon=True)
hist_thread.start()


# --- API Layer ---
app = FastAPI(title="Silent Photon API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/status")
def get_service_status():
    return {
        "status": "Online", 
        "mode": "Simulation Live", 
        "sim_status": "RUNNING" if sim_controller.running and not sim_controller.paused else "PAUSED"
    }

# --- SIMULATION CONTROLS ---

@app.post("/sim/control")
def control_sim(action: str = Body(..., embed=True), speed: Optional[float] = Body(None, embed=True)):
    """
    Control the simulation loop.
    Action: START, GRAVITY_PAUSE, RESUME, STEP
    Speed: Float multiplier (e.g. 1.0, 2.0, 5.0)
    """
    action = action.upper()
    if action == "PAUSE":
        sim_controller.pause()
    elif action == "RESUME" or action == "PLAY":
        sim_controller.resume()
    elif action == "STEP":
        sim_controller.step()
    elif action == "SPEED":
        if speed is not None:
            sim_controller.set_speed(speed)
    else:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    return {
        "status": "OK", 
        "paused": sim_controller.paused, 
        "speed": sim_controller.time_scale
    }

@app.get("/live")
def get_live_state():
    """Returns the full state of the Digital Twin."""
    network_state = []
    now = time.time()
    
    cap_mod = 1.0
    if gen.weather == "RAIN": cap_mod = 0.9
    elif gen.weather == "STORM": cap_mod = 0.75

    for l_id, link in mgr.twin.links.items():
        eff_cap = int(link.capacity * cap_mod)
        eff_ci = link.current_flow / eff_cap if eff_cap > 0 else 1.0
        
        age_sec = None
        if link.last_observation_ts:
            age_sec = max(0.0, now - link.last_observation_ts)

        last_source = link.last_observation_source if link.last_observation_ts else None

        network_state.append({
            "id": l_id,
            "name": link.name,
            "flow": int(link.current_flow),
            "capacity": eff_cap,
            "ci": round(eff_ci, 2),
            "price": link.current_price,
            "price_multiplier": round(link.price_multiplier, 2),
            "status": "CONGESTED" if eff_ci > 0.8 else "FLOWING",
            "type": getattr(link, "type", "road"),
            "diversion": int(getattr(link, "last_diversion", 0)),
            "is_live": l_id in mgr.policy.p_config.get('live_mode_links', []),
            "last_observation_at": link.last_observation_ts,
            "last_observation_source": last_source,
            "age_sec": age_sec,
            "coordinates": link.coordinates 
        })
    
    return {
        "timestamp": now,
        "sim_time": gen.get_virtual_time(), # This might need to be decoupled if we want time travel
        "weather": gen.weather,
        "events": list(gen.active_events.keys()),
        "links": network_state,
        "policy": {
            "sensitivity": mgr.policy.p_config.get('price_sensitivity_factor', 5.0),
            "aggressiveness": mgr.agent_aggressiveness,
            "live_stale_threshold_sec": mgr.policy.p_config.get('live_stale_threshold_sec', 10)
        },
        "control": {
            "paused": sim_controller.paused,
            "speed": sim_controller.time_scale
        }
    }

def _apply_live_links(link_ids: list[str]):
    mgr.policy.p_config['live_mode_links'] = link_ids
    if hasattr(mgr, "adapter"):
        mgr.adapter.set_live_links(link_ids)

if not mgr.policy.p_config.get('live_mode_links'):
    _apply_live_links(list(mgr.twin.links.keys()))

@app.get("/admin/links")
def list_links():
    links = []
    for link in mgr.twin.links.values():
        links.append({
            "id": link.id,
            "name": link.name,
            "type": link.type,
            "coordinates": link.coordinates
        })
    return {"links": links}

@app.get("/admin/live-links")
def get_live_links():
    live_links = mgr.policy.p_config.get('live_mode_links', [])
    return {"live_mode_links": live_links}

@app.post("/admin/live-links")
def set_live_links(update: LiveLinksUpdate):
    if update.mode and update.mode.lower() == "all":
        requested = list(mgr.twin.links.keys())
    else:
        requested = update.link_ids or []

    valid = [link_id for link_id in requested if link_id in mgr.twin.links]
    unknown = [link_id for link_id in requested if link_id not in mgr.twin.links]
    _apply_live_links(valid)
    return {"live_mode_links": valid, "unknown_links": unknown}

# --- ADMIN / GOD MODE ---

@app.post("/admin/agent/aggressiveness/{level}")
def set_aggressiveness(level: str):
    level = level.upper()
    if level == "LOW": val = 0.2
    elif level == "NORMAL": val = 1.0
    elif level == "HIGH": val = 3.0
    elif level == "EXTREME": val = 10.0
    else:
        raise HTTPException(status_code=400, detail="Use LOW, NORMAL, HIGH, EXTREME")
    
    mgr.agent_aggressiveness = val
    return {"message": f"Aggressiveness set to {val}x"}

@app.post("/admin/policy/sensitivity/nudge")
def nudge_sensitivity(amount: float = Body(..., embed=True)):
    curr = mgr.policy.p_config.get('price_sensitivity_factor', 5.0)
    new_val = max(1.0, min(20.0, curr + amount))
    mgr.policy.p_config['price_sensitivity_factor'] = new_val
    return {"message": f"Sensitivity nudged to {new_val}"}

@app.post("/simulate/accident")
def trigger_accident(link_id: Optional[str] = None):
    if not link_id:
        candidates = [l for l in mgr.twin.links.keys()]
        if not candidates: return {"error": "No links"}
        link_id = random.choice(candidates)

    if link_id not in mgr.twin.links:
        raise HTTPException(status_code=404, detail="Link not found")
    
    gen.trigger_accident(link_id)
    return {"message": f"Accident simulated on {link_id}"}

@app.post("/admin/weather/{weather_type}")
def set_weather(weather_type: str):
    if weather_type not in ["SUNNY", "RAIN", "STORM"]:
        raise HTTPException(status_code=400, detail="Invalid weather type")
    gen.weather = weather_type
    return {"message": f"Weather set to {weather_type}"}

@app.post("/admin/event/{event_name}")
def trigger_event(event_name: str):
    gen.active_events[event_name] = time.time() + 15.0
    return {"message": f"Event {event_name} started"}

@app.get("/stats/history")
def get_stats_history():
    return list(history)

# --- USER API ---

@app.get("/api/users")
def get_users():
    return list(mgr.twin.users.values())

@app.post("/api/quote")
def create_quote(user_id: str = Body(..., embed=True), link_id: str = Body(..., embed=True)):
    try:
        quote = mgr.service.create_quote(user_id, link_id)
        return quote
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/reserve")
def reserve_quote(quote_id: str = Body(..., embed=True)):
    try:
        reservation = mgr.service.reserve(quote_id)
        return reservation
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/confirm")
def confirm_reservation(reservation_id: str = Body(..., embed=True)):
    try:
        receipt = mgr.service.confirm(reservation_id)
        return receipt
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/ingest/speed")
def ingest_speed(link_id: str = Body(..., embed=True), speed: float = Body(..., embed=True)):
    """
    Manual/Scripted ingest for Live Traffic Data (Speed).
    Physics translation happens in the Adapter.
    """
    obs = TwinObservation(
        source="api-push",
        link_id=link_id,
        timestamp=time.time(),
        metric=MetricType.SPEED_KMH,
        value=speed
    )
    mgr.adapter.ingest(obs)
    
    # Return the calculated flow for debugging visibility
    link = mgr.twin.links.get(link_id)
    current_flow = link.current_flow if link else -1
    
    return {
        "status": "accepted",
        "link": link_id,
        "input_speed": speed,
        "translated_flow": current_flow
    }


# --- Static Files (Frontend) ---
# Mount 'web' directory to serve the UI
# Place this at the end so API routes take precedence
web_path = os.path.join(os.path.dirname(__file__), "web")
if os.path.exists(web_path):
    print(f"Serving frontend from {web_path}")
    app.mount("/", StaticFiles(directory=web_path, html=True), name="web")
else:
    print("Warning: 'web' directory not found. Frontend will not be served.")

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
