import argparse
import csv
import json
import math
import time
import zipfile
from io import TextIOWrapper
from pathlib import Path


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point_segment_distance_m(lat, lon, a_lat, a_lon, b_lat, b_lon):
    lat0 = lat
    r = 6371000.0
    ax = math.radians(a_lon - lon) * math.cos(math.radians(lat0)) * r
    ay = math.radians(a_lat - lat) * r
    bx = math.radians(b_lon - lon) * math.cos(math.radians(lat0)) * r
    by = math.radians(b_lat - lat) * r
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)
    t = -(ax * dx + ay * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx = ax + t * dx
    cy = ay + t * dy
    return math.hypot(cx, cy)


def distance_to_polyline(lat, lon, coords):
    best = None
    for i in range(len(coords) - 1):
        a_lat, a_lon = coords[i]
        b_lat, b_lon = coords[i + 1]
        dist = point_segment_distance_m(lat, lon, a_lat, a_lon, b_lat, b_lon)
        if best is None or dist < best:
            best = dist
    return best if best is not None else float("inf")


def load_links(config_path):
    with open(config_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    links = data.get("network", {}).get("links", [])
    records = []
    for link in links:
        coords = link.get("coordinates") or []
        if len(coords) < 2:
            continue
        mid = coords[len(coords) // 2]
        records.append({
            "id": link.get("id"),
            "coords": coords,
            "center": (mid[0], mid[1]),
        })
    return records


def build_link_grid(links, cell_deg):
    grid = {}
    for idx, link in enumerate(links):
        lat, lon = link["center"]
        cell = (int(lat / cell_deg), int(lon / cell_deg))
        grid.setdefault(cell, []).append(idx)
    return grid


def collect_candidates(lat, lon, grid, cell_deg, max_radius):
    cell = (int(lat / cell_deg), int(lon / cell_deg))
    for radius in range(0, max_radius + 1):
        candidates = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                candidates.extend(grid.get((cell[0] + dx, cell[1] + dy), []))
        if candidates:
            return candidates
    return []


def find_nearest_link(lat, lon, links, grid, cell_deg, neighbor_cells, max_distance_m, top_k):
    candidates = collect_candidates(lat, lon, grid, cell_deg, neighbor_cells)
    if not candidates:
        return None, None

    scored = []
    for idx in candidates:
        link = links[idx]
        c_lat, c_lon = link["center"]
        dist = haversine_m(lat, lon, c_lat, c_lon)
        scored.append((dist, idx))
    scored.sort(key=lambda x: x[0])

    best_id = None
    best_dist = None
    for _, idx in scored[:top_k]:
        link = links[idx]
        dist = distance_to_polyline(lat, lon, link["coords"])
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_id = link["id"]

    if best_dist is None or best_dist > max_distance_m:
        return None, None
    return best_id, best_dist


def load_csv(zf, name):
    with zf.open(name) as handle:
        reader = csv.DictReader(TextIOWrapper(handle, encoding="utf-8"))
        for row in reader:
            yield row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gtfs-zip", default="data/budapest_gtfs.zip")
    parser.add_argument("--config", default="full_city_config.json")
    parser.add_argument("--out-shape-map", default="data/bkk_shape_link_map.json")
    parser.add_argument("--out-trip-map", default="data/bkk_trip_shape_map.json")
    parser.add_argument("--out-route-map", default="data/bkk_route_shape_map.json")
    parser.add_argument("--cell-deg", type=float, default=0.004)
    parser.add_argument("--neighbor-cells", type=int, default=3)
    parser.add_argument("--max-distance-m", type=float, default=400.0)
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    links = load_links(args.config)
    if not links:
        raise SystemExit("No links found in config.")
    grid = build_link_grid(links, args.cell_deg)

    shape_points = {}
    trip_map = {}
    route_shapes = {}

    with zipfile.ZipFile(args.gtfs_zip, "r") as zf:
        for row in load_csv(zf, "shapes.txt"):
            shape_id = row.get("shape_id")
            if not shape_id:
                continue
            seq = int(row.get("shape_pt_sequence") or 0)
            lat = float(row.get("shape_pt_lat"))
            lon = float(row.get("shape_pt_lon"))
            shape_points.setdefault(shape_id, []).append((seq, lat, lon))

        for row in load_csv(zf, "trips.txt"):
            trip_id = row.get("trip_id")
            shape_id = row.get("shape_id")
            route_id = row.get("route_id")
            if trip_id and shape_id:
                trip_map[trip_id] = shape_id
            if route_id and shape_id:
                route_shapes.setdefault(route_id, set()).add(shape_id)

    shapes_out = {}
    missing = 0
    total_points = 0
    for shape_id, points in shape_points.items():
        ordered = sorted(points, key=lambda p: p[0])
        mapped_points = []
        link_ids = []
        last_link = None
        for _seq, lat, lon in ordered:
            total_points += 1
            link_id, dist = find_nearest_link(
                lat,
                lon,
                links,
                grid,
                args.cell_deg,
                args.neighbor_cells,
                args.max_distance_m,
                args.top_k,
            )
            if not link_id:
                missing += 1
                continue
            mapped_points.append([lat, lon, link_id])
            if link_id != last_link:
                link_ids.append(link_id)
                last_link = link_id
        if mapped_points:
            shapes_out[shape_id] = {
                "points": mapped_points,
                "link_ids": link_ids,
            }

    meta = {
        "created_at": time.time(),
        "cell_deg": args.cell_deg,
        "neighbor_cells": args.neighbor_cells,
        "max_distance_m": args.max_distance_m,
        "top_k": args.top_k,
        "total_points": total_points,
        "unmatched_points": missing,
    }

    Path(args.out_shape_map).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_shape_map, "w", encoding="utf-8") as handle:
        json.dump({"meta": meta, "shapes": shapes_out}, handle, separators=(",", ":"))
    with open(args.out_trip_map, "w", encoding="utf-8") as handle:
        json.dump(trip_map, handle, separators=(",", ":"))
    route_map = {route_id: sorted(list(shape_ids)) for route_id, shape_ids in route_shapes.items()}
    with open(args.out_route_map, "w", encoding="utf-8") as handle:
        json.dump(route_map, handle, separators=(",", ":"))

    print("shapes", len(shapes_out))
    print("trip_map", len(trip_map))
    print("route_map", len(route_map))
    print("points", total_points, "unmatched", missing)


if __name__ == "__main__":
    main()
