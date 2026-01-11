import time
import csv
import logging
from typing import List, Optional
from schemas import TwinObservation, MetricType

logger = logging.getLogger("csv_source")

class CSVPlaybackSource:
    """
    Reads a CSV file of traffic observations and pushes them to the TwinAdapter.
    Format: timestamp, link_id, speed_kmh
    """
    def __init__(self, adapter):
        self.adapter = adapter
    
    def process_row(self, link_id: str, speed: float):
        """
        Ingest a single speed observation.
        """
        obs = TwinObservation(
            source="csv-replay",
            link_id=link_id,
            timestamp=time.time(),
            metric=MetricType.SPEED_KMH,
            value=speed
        )
        self.adapter.ingest(obs)
        return True

    def run_file(self, filepath: str):
        """
        Single-pass run (blocking). good for testing.
        """
        with open(filepath, 'r') as f:
            reader = csv.reader(f)
            next(reader) # header
            for row in reader:
                # row = [timestamp, link_id, speed]
                if len(row) < 3: continue
                
                l_id = row[1]
                speed = float(row[2])
                
                self.process_row(l_id, speed)
                time.sleep(0.1) # Artifical delay

