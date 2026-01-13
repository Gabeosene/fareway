import heapq
import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class RoutePlan:
    link_ids: List[str]
    total_length_m: float
    visited_nodes: int


class RoutePlanner:
    def __init__(
        self,
        links: Iterable,
        connect_threshold_m: float = 40.0,
        cell_size_m: float = 80.0,
    ):
        self.connect_threshold_m = max(1.0, float(connect_threshold_m))
        self.cell_size_m = max(self.connect_threshold_m, float(cell_size_m))
        self.cell_deg = self.cell_size_m / 111000.0
        self._endpoint_cells: Dict[Tuple[int, int], List[Tuple[str, float, float]]] = {}
        self._endpoints: Dict[str, Tuple[List[float], List[float]]] = {}
        self._link_lengths: Dict[str, float] = {}
        self._graph: Dict[str, set[str]] = {}
        link_list = list(links)
        self._all_link_ids = {link.id for link in link_list}
        self._build(link_list)

    def _build(self, links: List) -> None:
        for link in links:
            coords = getattr(link, "coordinates", None)
            if not coords or len(coords) < 2:
                continue
            start = coords[0]
            end = coords[-1]
            if not self._valid_point(start) or not self._valid_point(end):
                continue
            self._endpoints[link.id] = (start, end)
            self._link_lengths[link.id] = self._polyline_length(coords)
            self._add_endpoint(link.id, start)
            self._add_endpoint(link.id, end)

        self._graph = {link_id: set() for link_id in self._endpoints.keys()}

        for link_id, (start, end) in self._endpoints.items():
            for point in (start, end):
                for other_id in self._nearby_links(point):
                    if other_id == link_id:
                        continue
                    if other_id not in self._graph:
                        continue
                    self._graph[link_id].add(other_id)
                    self._graph[other_id].add(link_id)

    def _valid_point(self, point: List[float]) -> bool:
        return isinstance(point, list) and len(point) >= 2

    def _add_endpoint(self, link_id: str, point: List[float]) -> None:
        lat = float(point[0])
        lon = float(point[1])
        cell = self._cell_key(lat, lon)
        self._endpoint_cells.setdefault(cell, []).append((link_id, lat, lon))

    def _cell_key(self, lat: float, lon: float) -> Tuple[int, int]:
        if self.cell_deg <= 0:
            return (0, 0)
        return (int(lat / self.cell_deg), int(lon / self.cell_deg))

    def _nearby_links(self, point: List[float]) -> Iterable[str]:
        lat = float(point[0])
        lon = float(point[1])
        cell = self._cell_key(lat, lon)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cell_key = (cell[0] + dx, cell[1] + dy)
                for link_id, o_lat, o_lon in self._endpoint_cells.get(cell_key, []):
                    if self._distance_m(lat, lon, o_lat, o_lon) <= self.connect_threshold_m:
                        yield link_id

    def _polyline_length(self, coords: List[List[float]]) -> float:
        total = 0.0
        for idx in range(1, len(coords)):
            a = coords[idx - 1]
            b = coords[idx]
            if not self._valid_point(a) or not self._valid_point(b):
                continue
            total += self._distance_m(a[0], a[1], b[0], b[1])
        return total

    def _distance_m(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def plan(self, start_link_id: str, end_link_id: str) -> Optional[RoutePlan]:
        if start_link_id not in self._all_link_ids:
            raise ValueError("Start link not found")
        if end_link_id not in self._all_link_ids:
            raise ValueError("End link not found")
        if start_link_id == end_link_id:
            length = self._link_lengths.get(start_link_id, 0.0)
            return RoutePlan([start_link_id], length, visited_nodes=1)
        if start_link_id not in self._graph or end_link_id not in self._graph:
            return None

        distances: Dict[str, float] = {}
        previous: Dict[str, str] = {}
        visited = set()
        heap: List[Tuple[float, str]] = []

        start_cost = self._link_lengths.get(start_link_id, 0.0)
        distances[start_link_id] = start_cost
        heapq.heappush(heap, (start_cost, start_link_id))

        while heap:
            current_cost, link_id = heapq.heappop(heap)
            if link_id in visited:
                continue
            visited.add(link_id)

            if link_id == end_link_id:
                break

            for neighbor in self._graph.get(link_id, []):
                if neighbor in visited:
                    continue
                neighbor_cost = self._link_lengths.get(neighbor, 0.0)
                candidate = current_cost + neighbor_cost
                if candidate < distances.get(neighbor, float("inf")):
                    distances[neighbor] = candidate
                    previous[neighbor] = link_id
                    heapq.heappush(heap, (candidate, neighbor))

        if end_link_id not in distances:
            return None

        path = [end_link_id]
        while path[-1] != start_link_id:
            prev = previous.get(path[-1])
            if prev is None:
                return None
            path.append(prev)
        path.reverse()

        return RoutePlan(path, distances[end_link_id], visited_nodes=len(visited))

    def route_length(self, link_ids: Iterable[str]) -> float:
        return sum(self._link_lengths.get(link_id, 0.0) for link_id in link_ids)
