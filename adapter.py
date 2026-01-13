from typing import Dict, List, Optional
import time
from schemas import TwinObservation, MetricType
import logging

logger = logging.getLogger("twin_adapter")

class TwinAdapter:
    """
    The Universal Translator.
    Accepts standardized TwinObservations (Speed, Flow, etc.)
    and updates the CongestionTwin state (Flow-based).
    """
    def __init__(self, manager):
        self.mgr = manager
        self.live_mode_links = set(manager.policy.p_config.get('live_mode_links', []))

    def set_live_links(self, link_ids):
        self.live_mode_links = set(link_ids or [])

    def _is_live_source(self, source: str) -> bool:
        source = (source or "").lower()
        return source.startswith(("live", "api", "bkk", "tomtom"))

    def ingest(self, obs: TwinObservation) -> bool:
        # 1. Routing Strategy: Hybrid Mode
        # If a link is set to "Live Mode", ignore Synthetic (sim) inputs
        source = (obs.source or "").lower()
        is_sim = source.startswith("sim")
        is_live = self._is_live_source(source)
        if obs.link_id in self.live_mode_links:
            if is_sim:
                return False # Block synthetic data for live links
        elif is_live:
            return False # Block live data for simulated links
        
        # 2. Validation
        if obs.link_id not in self.mgr.twin.links:
            # logger.warning(f"Unknown link ID: {obs.link_id}")
            return False

        # 3. Physics Translation
        final_flow = 0
        link = self.mgr.twin.links[obs.link_id]

        if obs.metric == MetricType.FLOW_VEH_PER_HOUR:
            final_flow = int(obs.value)
        
        elif obs.metric == MetricType.SPEED_KMH:
            final_flow = self._speed_to_flow(obs.value, link)
            
        elif obs.metric == MetricType.TRAVEL_TIME_SEC:
             # Just convert TT to speed roughly: Speed = Dist / Time
             # We don't have Distance readily available in simple Link model (only coords).
             # For now, let's assume we can't reliably do this without length.
             # SKIP.
             return False

        # 4. Update Twin
        # We apply the update immediately. 
        # Future: Add smoothing/EMA here if live data is jittery.
        self.mgr.twin.ingest_observation(
            obs.link_id,
            final_flow,
            source=obs.source,
            timestamp=obs.timestamp
        )
        return True

    def _speed_to_flow(self, speed_kmh: float, link) -> int:
        """
        Approximates Flow from Speed using an inverse Fundamental Diagram.
        
        Logic: 
        - Low Speed = High Congestion (High Flow Equivalent)
        - High Speed = Low Congestion (Low Flow Equivalent)
        
        Using a linear Greenshields-like approximation for the demo.
        CI = 1.0 - (Speed / FreeFlowSpeed)
        """
        # 1. Determine Free Flow Speed
        # If not in config, assume standard urban limits
        free_flow = 50.0 
        if "highway" in link.type: free_flow = 90.0
        elif "primary" in link.type: free_flow = 60.0
        
        # Clamp speed
        speed_kmh = max(0.0, min(speed_kmh, free_flow))
        
        # 2. Calculate Congestion Index (CI)
        # If speed is 0, CI is 1.0. If speed is FreeFlow, CI is 0.0.
        ci = 1.0 - (speed_kmh / free_flow)
        
        # 3. Convert to "Equivalent Flow"
        # The Twin logic uses: CI = Flow / Capacity
        # So: Flow = CI * Capacity
        equiv_flow = int(ci * link.capacity)
        
        return max(0, equiv_flow)
