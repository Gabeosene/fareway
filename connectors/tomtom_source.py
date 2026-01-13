import json
import logging
import threading
import time
from itertools import cycle
from typing import Iterable, Optional
from urllib.parse import quote
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

from schemas import MetricType, TwinObservation

logger = logging.getLogger("tomtom_source")

class TomTomSource:
    """
    Polls TomTom Traffic Flow API for real-time speed data.
    Uses a round-robin approach to respect API rate limits.
    """

    def __init__(
        self,
        adapter,
        links: Iterable,
        api_key: str,
        poll_interval: float = 5.0, # Default to 5s between calls to keep it chill
    ):
        self.adapter = adapter
        self.api_key = api_key
        self.poll_interval = poll_interval
        
        # Build list of pollable candidates (must have coords)
        self.targets = []
        for link in links:
             # We need a representative point. Let's take the middle coordinate.
            coords = getattr(link, "coordinates", [])
            if not coords or len(coords) < 1:
                continue
            
            # Find midpoint
            mid_idx = len(coords) // 2
            mid_point = coords[mid_idx]
            
            if len(mid_point) >= 2:
                self.targets.append({
                    "id": link.id,
                    "lat": round(mid_point[0], 5), # Round to maximize cache hits if points are close
                    "lon": round(mid_point[1], 5)
                })
        self._all_targets = list(self.targets)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._target_cycle = cycle(self.targets) if self.targets else None
        
        # Caching
        self.cache_ttl = 60.0 # Seconds
        self._cache = {} # Key: (lat, lon), Value: (timestamp, payload)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.targets:
            logger.warning("TomTom source has no links with valid coordinates to poll.")
            return
            
        logger.info(f"Starting TomTom Source with {len(self.targets)} targets. Interval: {self.poll_interval}s")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def set_link_ids(self, link_ids: Iterable[str]):
        ids = set(link_ids) if link_ids else set()
        if ids:
            self.targets = [t for t in self._all_targets if t["id"] in ids]
        else:
            self.targets = list(self._all_targets)
        self._target_cycle = cycle(self.targets) if self.targets else None

    def _fetch_flow(self, lat: float, lon: float) -> Optional[dict]:
        # Check Cache
        now = time.time()
        key = (lat, lon)
        if key in self._cache:
            ts, payload = self._cache[key]
            if now - ts < self.cache_ttl:
                # logger.debug(f"Cache hit for {lat},{lon}")
                return payload
        
        # API: https://developer.tomtom.com/traffic-api/documentation/traffic-flow/flow-segment-data
        # URL: https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?point=lat,lon&key=key
        
        base_url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
        query = f"?point={lat},{lon}&key={self.api_key}"
        url = base_url + query
        
        try:
            req = Request(url)
            # Add User-Agent just in case
            req.add_header('User-Agent', 'SilentPhoton/1.0')
            
            with urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    self._cache[key] = (now, data)
                    return data
                else:
                    logger.warning(f"TomTom API returned status {response.status}")
                    return None
                    
        except HTTPError as e:
            if e.code == 429:
                logger.warning("TomTom API Rate Limit Exceeded! Backing off...")
                time.sleep(10.0) # Penalty wait
            else:
                logger.warning(f"TomTom API HTTP Error: {e.code}")
            return None
        except URLError as e:
            logger.warning(f"TomTom API Connection Error: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"TomTom API Unexpected Error: {e}")
            return None

    def _run(self):
        while not self._stop_event.is_set():
            if not self._target_cycle:
                time.sleep(self.poll_interval)
                continue
                
            # Get next target
            target = next(self._target_cycle)
            
            # Poll
            payload = self._fetch_flow(target["lat"], target["lon"])
            
            if payload and "flowSegmentData" in payload:
                data = payload["flowSegmentData"]
                # Extract speeds
                # currentSpeed is in km/h (check units in doc, typically yes if not specified otherwise, 
                # but TomTom usually returns km/h or m/s depending on unit param. Default is KPH)
                
                # Check units? The doc says "unit" default is KMPH.
                
                current_speed = data.get("currentSpeed")
                free_flow = data.get("freeFlowSpeed")
                confidence = data.get("confidence", 0.0) # 0 to 1
                
                if current_speed is not None:
                    obs = TwinObservation(
                        source="tomtom-api",
                        link_id=target["id"],
                        timestamp=time.time(),
                        metric=MetricType.SPEED_KMH,
                        value=float(current_speed)
                    )
                    self.adapter.ingest(obs)
                    # logger.info(f"Updated {target['id']}: {current_speed} km/h")
            
            # Wait
            time.sleep(self.poll_interval)
