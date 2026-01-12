import json
import logging
import threading
import time
from itertools import cycle
from typing import Iterable, Optional
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

from schemas import MetricType, TwinObservation

logger = logging.getLogger("live_source")


class LiveAPISource:
    """
    Polls an external API and emits TwinObservation updates.
    """

    def __init__(
        self,
        adapter,
        link_ids: Iterable[str],
        poll_interval: float = 2.5,
        api_url: str = "https://worldtimeapi.org/api/timezone/Etc/UTC",
    ):
        self.adapter = adapter
        self.link_ids = list(link_ids)
        self.poll_interval = poll_interval
        self.api_url = self._normalize_api_url(api_url)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._link_cycle = cycle(self.link_ids) if self.link_ids else None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.link_ids:
            logger.warning("Live source has no link IDs to publish observations.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def set_link_ids(self, link_ids: Iterable[str]):
        self.link_ids = list(link_ids)
        self._link_cycle = cycle(self.link_ids) if self.link_ids else None
        if not self.link_ids:
            self.stop()
            return
        if not self._thread or not self._thread.is_alive():
            self.start()

    def _normalize_api_url(self, api_url: str) -> str:
        parsed = urlparse(api_url)
        if parsed.path.endswith("/Etc/UT"):
            corrected_path = f"{parsed.path}C"
            return urlunparse(parsed._replace(path=corrected_path))
        return api_url

    def _fetch_external_payload(self) -> Optional[dict]:
        try:
            api_url = self._normalize_api_url(self.api_url)
            with urlopen(api_url, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("Live source API poll failed: %s", exc)
            return None

    def _build_observation(
        self,
        payload: Optional[dict],
        link_cycle: Optional[Iterable[str]] = None,
    ) -> TwinObservation:
        now = time.time()
        unixtime = payload.get("unixtime") if payload else None
        source_ts = float(unixtime) if unixtime is not None else now
        speed_seed = int(unixtime) if unixtime is not None else int(now * 10)
        speed_kmh = 20.0 + (speed_seed % 70)
        cycle_iter = link_cycle or self._link_cycle
        if not cycle_iter:
            raise RuntimeError("Live source has no active link cycle.")
        link_id = next(cycle_iter)
        return TwinObservation(
            source="live-api",
            link_id=link_id,
            timestamp=source_ts,
            metric=MetricType.SPEED_KMH,
            value=speed_kmh,
        )

    def _run(self):
        while not self._stop_event.is_set():
            link_cycle = self._link_cycle
            if not link_cycle:
                time.sleep(self.poll_interval)
                continue
            payload = self._fetch_external_payload()
            try:
                obs = self._build_observation(payload, link_cycle=link_cycle)
            except Exception as exc:
                logger.warning("Live source failed to build observation: %s", exc)
                time.sleep(self.poll_interval)
                continue
            if obs:
                self.adapter.ingest(obs)
            time.sleep(self.poll_interval)
