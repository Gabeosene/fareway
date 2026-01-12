import math
import random
import time
from typing import Dict, Optional

class TrafficGenerator:
    def __init__(self):
        self.noise_level = 0.05
        self.cycle_duration = 30 # seconds for a full "day" in simulation (fast!)
        self.start_time = time.time()
        self.accidents: Dict[str, float] = {} # link_id -> expiration_time
        
        # Phase 7: Environment
        self.weather = "SUNNY" # SUNNY, RAIN, STORM
        self.active_events: Dict[str, float] = {} # event_name -> expiration_time

    def get_flow(self, link_id: str, capacity: int, current_time: float) -> int:
        # 1. Base Sine Wave (Day/Night cycle)
        # Shifted so it starts low, goes high, goes low
        elapsed = current_time - self.start_time
        phase = (elapsed % self.cycle_duration) / self.cycle_duration * 2 * math.pi
        
        # sin(phase - pi/2) goes from -1 to 1. 
        # +1 -> 0 to 2. /2 -> 0 to 1.
        # We want a base load of roughly 20% to 90%
        base_factor = 0.2 + 0.7 * ((math.sin(phase - math.pi/2) + 1) / 2)

        # 2. Add Noise
        noise = random.uniform(-self.noise_level, self.noise_level)
        
        # 3. Add Accidents
        accident_factor = 0.0
        if link_id in self.accidents:
            if current_time > self.accidents[link_id]:
                del self.accidents[link_id]
            else:
                accident_factor = 0.7 # Add 70% capacity load (massive jam)
                
        # 4. Add Events
        event_factor = 0.0
        # Check active events
        expired_events = []
        for evt, exp in self.active_events.items():
            if current_time > exp:
                expired_events.append(evt)
            else:
                # Match Day Logic
                if evt == "MATCH" and link_id in ["link_hungaria", "link_m4"]:
                    event_factor += 0.4 # +40% flow
        
        for e in expired_events:
            del self.active_events[e]

        total_factor = base_factor + noise + accident_factor + event_factor
        
        # Ensure bounds
        total_factor = max(0.0, total_factor)
        # We allow > 1.0 (over capacity)

        return int(capacity * total_factor)

    def get_virtual_time(self, current_time: Optional[float] = None) -> str:
        """Returns the current simulation time as a HH:MM string."""
        now = current_time if current_time is not None else time.time()
        elapsed = now - self.start_time
        cycle_progress = (elapsed % self.cycle_duration) / self.cycle_duration
        
        # Map 0..1 to 0..24 hours
        total_minutes = int(cycle_progress * 24 * 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        
        return f"{hours:02d}:{minutes:02d}"

    def trigger_accident(self, link_id: str, duration: float = 8.0):
        """Triggers a massive congestion spike on the link for `duration` seconds."""
        self.accidents[link_id] = time.time() + duration
