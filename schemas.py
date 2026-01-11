from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class MetricType(str, Enum):
    SPEED_KMH = "SPEED_KMH"
    FLOW_VEH_PER_HOUR = "FLOW_VEH_PER_HOUR"
    TRAVEL_TIME_SEC = "TRAVEL_TIME_SEC"

@dataclass
class TwinObservation:
    source: str  # e.g., "sim-gen", "waze-live", "csv-replay"
    link_id: str
    timestamp: float
    metric: MetricType
    value: float
    confidence: float = 1.0  # 1.0 = Observed, 0.5 = Interpolated/Projected
