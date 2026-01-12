import json
import logging
import math
import os
import threading
import time
from typing import Iterable, Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
from urllib.request import urlopen

from schemas import MetricType, TwinObservation

logger = logging.getLogger("bkk_source")


class BkkLiveSource:
    """
    Polls BKK GTFS-RT feeds and emits TwinObservation updates.
    """

    def __init__(
        self,
        adapter,
        links: Iterable,
        api_key: str,
        poll_interval: float = 10.0,
        api_url: str = "https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/VehiclePositions.pb",
        max_match_m: float = 150.0,
        link_types: Optional[set[str]] = None,
        shape_map_path: Optional[str] = None,
        trip_map_path: Optional[str] = None,
        route_map_path: Optional[str] = None,
        trip_updates_url: Optional[str] = None,
        alerts_url: Optional[str] = None,
        enable_trip_updates: bool = True,
        enable_alerts: bool = True,
    ):
        self.adapter = adapter
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.api_url = api_url
        self.max_match_m = max_match_m
        self.link_types = link_types
        self.shape_map_path = shape_map_path or "data/bkk_shape_link_map.json"
        self.trip_map_path = trip_map_path or "data/bkk_trip_shape_map.json"
        self.route_map_path = route_map_path or "data/bkk_route_shape_map.json"
        self.trip_updates_url = trip_updates_url or "https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/TripUpdates.pb"
        self.alerts_url = alerts_url or "https://go.bkk.hu/api/query/v1/ws/gtfs-rt/full/Alerts.pb"
        self.enable_trip_updates = enable_trip_updates
        self.enable_alerts = enable_alerts
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._link_centers = []
        self._active_link_ids: Optional[set[str]] = None
        self._shape_map = {}
        self._trip_shape_map = {}
        self._route_shape_map = {}
        self._shape_index = {}
        self._last_vehicle_poll = None
        self._vehicle_count = 0
        self._trip_updates_status = None
        self._alerts_status = None
        self._build_link_centers(links)
        self._load_mapping()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self._link_centers:
            logger.warning("BKK live source has no link centers to match.")
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
        ids = set(link_ids)
        self._active_link_ids = ids if ids else None

    def get_status(self):
        return {
            "last_vehicle_poll": self._last_vehicle_poll,
            "vehicle_count": self._vehicle_count,
            "trip_updates": self._trip_updates_status,
            "alerts": self._alerts_status,
        }

    def _build_link_centers(self, links: Iterable):
        allowed_types = self.link_types if self.link_types is not None else {"transit"}
        centers = []
        for link in links:
            link_type = getattr(link, "type", "road")
            if allowed_types and link_type not in allowed_types:
                continue
            coords = getattr(link, "coordinates", None)
            if not coords or len(coords) < 2:
                continue
            mid = coords[len(coords) // 2]
            if not isinstance(mid, (list, tuple)) or len(mid) < 2:
                continue
            centers.append({
                "id": link.id,
                "lat": float(mid[0]),
                "lon": float(mid[1]),
            })
        if not centers and allowed_types == {"transit"}:
            for link in links:
                coords = getattr(link, "coordinates", None)
                if not coords or len(coords) < 2:
                    continue
                mid = coords[len(coords) // 2]
                if not isinstance(mid, (list, tuple)) or len(mid) < 2:
                    continue
                centers.append({
                    "id": link.id,
                    "lat": float(mid[0]),
                    "lon": float(mid[1]),
                })
            if centers:
                logger.warning("No transit links found; using all links for BKK matching.")
        self._link_centers = centers

    def _load_mapping(self):
        self._shape_map = self._load_json(self.shape_map_path).get("shapes", {})
        self._trip_shape_map = self._load_json(self.trip_map_path)
        self._route_shape_map = self._load_json(self.route_map_path)
        if not self._shape_map:
            logger.warning("BKK mapping not found; falling back to nearest-link matching.")
            return
        for shape_id, shape_data in self._shape_map.items():
            points = shape_data.get("points", [])
            if not points:
                continue
            self._shape_index[shape_id] = self._build_shape_index(points)

    def _load_json(self, path: str):
        try:
            if not path or not os.path.exists(path):
                return {}
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", path, exc)
            return {}

    def _build_shape_index(self, points, cell_deg: float = 0.001):
        cells = {}
        min_lat = min(p[0] for p in points)
        max_lat = max(p[0] for p in points)
        min_lon = min(p[1] for p in points)
        max_lon = max(p[1] for p in points)
        for idx, (lat, lon, _link_id) in enumerate(points):
            cell = (int(lat / cell_deg), int(lon / cell_deg))
            cells.setdefault(cell, []).append(idx)
        return {
            "cell_deg": cell_deg,
            "cells": cells,
            "bbox": (min_lat, max_lat, min_lon, max_lon),
            "points": points,
        }

    def _with_key(self, url: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query))
        if "key" not in query:
            query["key"] = self.api_key
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _fetch_payload(self, url: str) -> Optional[bytes]:
        try:
            url = self._with_key(url)
            with urlopen(url, timeout=10) as response:
                return response.read()
        except Exception as exc:
            logger.warning("BKK live source poll failed: %s", exc)
            return None

    def _parse_feed(self, payload: bytes):
        try:
            from google.transit import gtfs_realtime_pb2  # type: ignore
        except Exception as exc:
            logger.warning("Missing GTFS-RT protobuf bindings: %s", exc)
            return None

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(payload)
        return feed

    def _haversine_m(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _find_nearest_link(self, lat: float, lon: float) -> Optional[tuple[str, float]]:
        best = None
        for center in self._link_centers:
            link_id = center["id"]
            if self._active_link_ids and link_id not in self._active_link_ids:
                continue
            dist = self._haversine_m(lat, lon, center["lat"], center["lon"])
            if best is None or dist < best[1]:
                best = (link_id, dist)
        return best

    def _find_shape_link(self, shape_id: str, lat: float, lon: float) -> Optional[tuple[str, float]]:
        info = self._shape_index.get(shape_id)
        if not info:
            return None
        min_lat, max_lat, min_lon, max_lon = info["bbox"]
        if lat < min_lat - 0.01 or lat > max_lat + 0.01 or lon < min_lon - 0.01 or lon > max_lon + 0.01:
            return None
        cell_deg = info["cell_deg"]
        cell = (int(lat / cell_deg), int(lon / cell_deg))
        cells = info["cells"]
        points = info["points"]
        candidate_indices = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidate_indices.extend(cells.get((cell[0] + dx, cell[1] + dy), []))
        if not candidate_indices:
            candidate_indices = range(len(points))

        best = None
        for idx in candidate_indices:
            p_lat, p_lon, link_id = points[idx]
            if self._active_link_ids and link_id not in self._active_link_ids:
                continue
            dist = self._haversine_m(lat, lon, p_lat, p_lon)
            if best is None or dist < best[1]:
                best = (link_id, dist)
        return best

    def _extract_trip_descriptor(self, vehicle):
        if not vehicle.HasField("trip"):
            return None
        return vehicle.trip

    def _resolve_shape_id(self, trip_desc) -> Optional[str]:
        if trip_desc is None:
            return None
        trip_id = trip_desc.trip_id if hasattr(trip_desc, "trip_id") else None
        if trip_id:
            shape_id = self._trip_shape_map.get(trip_id)
            if shape_id:
                return shape_id
        route_id = trip_desc.route_id if hasattr(trip_desc, "route_id") else None
        if route_id:
            shapes = self._route_shape_map.get(route_id)
            if shapes:
                return shapes[0]
        return None

    def _extract_alert_text(self, text_field) -> str:
        if not text_field or not getattr(text_field, "translation", None):
            return ""
        for translation in text_field.translation:
            if translation.text:
                return translation.text
        return ""

    def _update_trip_updates(self):
        payload = self._fetch_payload(self.trip_updates_url)
        if not payload:
            return
        feed = self._parse_feed(payload)
        if feed is None:
            return

        route_stats = {}
        total_delay = 0
        delay_count = 0
        max_delay = 0
        trip_count = 0

        for entity in feed.entity:
            if not entity.HasField("trip_update"):
                continue
            tu = entity.trip_update
            trip_desc = tu.trip
            route_id = trip_desc.route_id if hasattr(trip_desc, "route_id") else "unknown"
            delays = []
            if hasattr(tu, "delay") and tu.delay:
                delays.append(int(tu.delay))
            for update in tu.stop_time_update:
                if update.arrival and update.arrival.delay:
                    delays.append(int(update.arrival.delay))
                if update.departure and update.departure.delay:
                    delays.append(int(update.departure.delay))
            if not delays:
                continue
            trip_delay = int(sum(delays) / len(delays))
            stats = route_stats.setdefault(route_id, {"count": 0, "sum": 0, "max": 0})
            stats["count"] += 1
            stats["sum"] += trip_delay
            stats["max"] = max(stats["max"], trip_delay)
            total_delay += trip_delay
            delay_count += 1
            max_delay = max(max_delay, trip_delay)
            trip_count += 1

        route_summary = {}
        for route_id, stats in route_stats.items():
            avg = stats["sum"] / stats["count"] if stats["count"] else 0
            route_summary[route_id] = {
                "trip_count": stats["count"],
                "avg_delay_sec": round(avg, 2),
                "max_delay_sec": stats["max"],
            }

        self._trip_updates_status = {
            "timestamp": time.time(),
            "trip_count": trip_count,
            "avg_delay_sec": round(total_delay / delay_count, 2) if delay_count else 0,
            "max_delay_sec": max_delay,
            "routes": route_summary,
        }

    def _update_alerts(self):
        payload = self._fetch_payload(self.alerts_url)
        if not payload:
            return
        feed = self._parse_feed(payload)
        if feed is None:
            return

        alerts = []
        for entity in feed.entity:
            if not entity.HasField("alert"):
                continue
            alert = entity.alert
            header = self._extract_alert_text(alert.header_text)
            desc = self._extract_alert_text(alert.description_text)
            effect = int(alert.effect) if hasattr(alert, "effect") else 0
            informed = []
            for item in alert.informed_entity:
                route_id = item.route_id if hasattr(item, "route_id") else ""
                stop_id = item.stop_id if hasattr(item, "stop_id") else ""
                if route_id or stop_id:
                    informed.append({"route_id": route_id, "stop_id": stop_id})
            alerts.append({
                "header": header,
                "description": desc,
                "effect": effect,
                "informed_entity": informed,
            })

        self._alerts_status = {
            "timestamp": time.time(),
            "count": len(alerts),
            "alerts": alerts[:50],
        }

    def _run(self):
        while not self._stop_event.is_set():
            payload = self._fetch_payload(self.api_url)
            if not payload:
                time.sleep(self.poll_interval)
                continue

            feed = self._parse_feed(payload)
            if feed is None:
                time.sleep(self.poll_interval)
                continue

            best_for_link = {}
            vehicle_count = 0

            for entity in feed.entity:
                if not entity.HasField("vehicle"):
                    continue
                vehicle = entity.vehicle
                if not vehicle.HasField("position"):
                    continue
                pos = vehicle.position
                if not pos.HasField("latitude") or not pos.HasField("longitude"):
                    continue
                if not pos.HasField("speed"):
                    continue

                vehicle_count += 1
                lat = float(pos.latitude)
                lon = float(pos.longitude)
                link_id = None
                dist = None

                shape_id = None
                if self._shape_index:
                    trip_desc = self._extract_trip_descriptor(vehicle)
                    shape_id = self._resolve_shape_id(trip_desc)
                if shape_id:
                    shape_match = self._find_shape_link(shape_id, lat, lon)
                    if shape_match:
                        link_id, dist = shape_match

                if not link_id:
                    nearest = self._find_nearest_link(lat, lon)
                    if not nearest:
                        continue
                    link_id, dist = nearest

                if dist is None or dist > self.max_match_m:
                    continue

                speed_kmh = float(pos.speed) * 3.6
                ts = float(vehicle.timestamp) if vehicle.HasField("timestamp") else time.time()
                obs = TwinObservation(
                    source="bkk-gtfs-rt",
                    link_id=link_id,
                    timestamp=ts,
                    metric=MetricType.SPEED_KMH,
                    value=speed_kmh,
                )

                prev = best_for_link.get(link_id)
                if not prev or dist < prev[1]:
                    best_for_link[link_id] = (obs, dist)

            for obs, _ in best_for_link.values():
                self.adapter.ingest(obs)

            self._last_vehicle_poll = time.time()
            self._vehicle_count = vehicle_count

            if self.enable_trip_updates:
                self._update_trip_updates()
            if self.enable_alerts:
                self._update_alerts()

            time.sleep(self.poll_interval)
