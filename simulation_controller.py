import time
import threading
import logging
from typing import Optional
from schemas import TwinObservation, MetricType

logger = logging.getLogger("sim_controller")

class SimulationController:
    """
    Manages the main simulation loop with support for:
    - Pause/Resume
    - Time Scaling (Speed)
    - Step-by-step execution
    """
    def __init__(self, manager_instance, generator_instance):
        self.mgr = manager_instance
        self.gen = generator_instance
        
        # Control State
        self.running = False
        self.paused = False
        self.time_scale = 1.0 # 1.0 = Realtime (or base tick rate)
        self.target_tick_rate = 2.0 # Hz (Ticks per second)
        
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._step_event = threading.Event() # For single stepping
        
        # Stats
        self.last_tick_duration = 0.0
        self.sim_time = time.time()

    def start(self):
        if self.running:
            return
        
        self.running = True
        self.paused = False
        self._stop_event.clear()
        
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[SimController] Simulation started.")

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        print("[SimController] Simulation stopped.")

    def pause(self):
        self.paused = True
        print("[SimController] Simulation paused.")

    def resume(self):
        self.paused = False
        print("[SimController] Simulation resumed.")

    def set_speed(self, speed: float):
        self.time_scale = max(0.1, min(speed, 50.0))
        print(f"[SimController] Speed set to {self.time_scale}x")

    def step(self):
        """Advance one tick if paused."""
        if self.paused:
            period = 1.0 / self.target_tick_rate
            self._advance_sim_time(period)
            self._run_tick(sim_time=self.sim_time)

    def _advance_sim_time(self, real_elapsed: float):
        if real_elapsed <= 0:
            return
        self.sim_time += real_elapsed * self.time_scale

    def _loop(self):
        last_real_time = time.time()
        while not self._stop_event.is_set():
            if self.paused:
                last_real_time = time.time()
                time.sleep(0.1)
                continue

            start_time = time.time()
            real_elapsed = start_time - last_real_time
            last_real_time = start_time
            self._advance_sim_time(real_elapsed)
            
            # Execute Logic
            self._run_tick(sim_time=self.sim_time)
            
            # Sleep to maintain rate (adjusted by time_scale)
            # Base rate is target_tick_rate (e.g. 2Hz = 0.5s period)
            # If speed is 2x, period is 0.25s
            
            period = (1.0 / self.target_tick_rate) / self.time_scale
            elapsed = time.time() - start_time
            self.last_tick_duration = elapsed
            
            sleep_time = max(0.0, period - elapsed)
            time.sleep(sleep_time)

    def _run_tick(self, sim_time: Optional[float] = None):
        # 1. Update Traffic Flows
        # We need to access the logic that was previously in server.py
        # For now, we'll assume the manager/generator has the logic or we execute it here.
        # Ideally, this logic should be in a "Systems" class, but we will adapt the existing logic.
        
        now = time.time()
        sim_now = sim_time if sim_time is not None else self.sim_time
        live_mode_links = set(self.mgr.policy.p_config.get('live_mode_links', []))
        if hasattr(self.mgr, "adapter"):
            live_mode_links = set(getattr(self.mgr.adapter, "live_mode_links", live_mode_links))
        
        # --- LOGIC MOVED FROM SERVER.PY ---
        total_shifting_demand = 0.0
        metro_flow = None
        
        # 1. Traffic Generation & Diversion
        for link_id, link in self.mgr.twin.links.items():
            if link_id in live_mode_links:
                continue

            # Get base flow
            # Note: Generator expects real time usually, but let's pass 'now'
            # If we want "Virtual Time", we should track it separately. 
            # For now, keeping it simple.
            base_flow = self.gen.get_flow(link_id, link.capacity, sim_now)
            
            shifted_flow = 0
            if link.price_multiplier > 1.0:
                excess_p = link.price_multiplier - 1.0
                diversion_pct = min(0.9, excess_p * 0.4)
                shifted_flow = base_flow * diversion_pct
            
            sim_flow = base_flow - shifted_flow
            link.last_diversion = shifted_flow 
            
            if "Bridge" in link.name or "Ring" in link.name:
                total_shifting_demand += shifted_flow
            
            if link_id == "link_m4":
                metro_flow = sim_flow
                continue

            # [REFACTORED] Send to Adapter
            obs = TwinObservation(
                source="sim-gen",
                link_id=link_id,
                timestamp=now,
                metric=MetricType.FLOW_VEH_PER_HOUR,
                value=sim_flow
            )
            self.mgr.adapter.ingest(obs)
            
        # 2. Metro Absorption
        metro = self.mgr.twin.links.get("link_m4")
        if metro and "link_m4" not in live_mode_links and metro_flow is not None:
            metro_flow += total_shifting_demand
            metro.last_diversion = -total_shifting_demand

            # [REFACTORED] Send to Adapter
            obs = TwinObservation(
                source="sim-gen",
                link_id="link_m4",
                timestamp=now,
                metric=MetricType.FLOW_VEH_PER_HOUR,
                value=metro_flow
            )
            self.mgr.adapter.ingest(obs)
            
        # 3. Market Tick
        self.mgr.twin.tick()
        
        # 4. Agent Logic (Smart Optimizer)
        self._run_agent_logic()
        
    def _run_agent_logic(self):
        # Re-implementing the simple agent from server.py
        # accessing global 'agent_aggressiveness' is tricky if it's in server.py
        # We will need to store aggressiveness here or in manager.
        
        # For now, let's assume it's stored in self.mgr.policy for better architecture
        # Or we can just do a simple valid implementation here.
        
        link_cis = [l.current_ci for l in self.mgr.twin.links.values()]
        avg_ci = sum(link_cis) / len(link_cis) if link_cis else 0
        
        current_sensitivity = self.mgr.policy.p_config.get('price_sensitivity_factor', 5.0)
        aggressiveness = getattr(self.mgr, 'agent_aggressiveness', 1.0) # We will attach this to mgr

        step = 0.0
        if avg_ci > 0.6:
            if avg_ci > 0.85: step = 2.0 
            elif avg_ci > 0.75: step = 0.5
            else: step = 0.1 
        elif avg_ci < 0.4:
            if avg_ci < 0.2: step = -1.0
            elif avg_ci < 0.3: step = -0.3
            else: step = -0.1
            
        step *= aggressiveness
        current_sensitivity = max(1.0, min(20.0, current_sensitivity + step))
        self.mgr.policy.p_config['price_sensitivity_factor'] = current_sensitivity
