import argparse
import csv
import json
import time
import zipfile
from collections import Counter, defaultdict
from io import TextIOWrapper
from pathlib import Path

MODE_DEFAULTS = {
    "0": ("Tram", 6000, 300),
    "1": ("Metro", 15000, 450),
    "2": ("Rail", 8000, 350),
    "3": ("Bus", 4000, 250),
    "4": ("Ferry", 2000, 250),
    "5": ("Cable", 2000, 250),
    "6": ("Gondola", 2000, 250),
    "7": ("Funicular", 2000, 250),
    "11": ("Trolleybus", 4000, 250),
}


def load_csv(zf, name):
    with zf.open(name) as handle:
        reader = csv.DictReader(TextIOWrapper(handle, encoding="utf-8"))
        for row in reader:
            yield row


def ascii_or_empty(value: str) -> str:
    if not value:
        return ""
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        return ""


def pick_route_id(counter: Counter) -> str:
    if not counter:
        return ""
    return max(counter.items(), key=lambda item: item[1])[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gtfs-zip", default="data/budapest_gtfs.zip")
    parser.add_argument("--out-links", default="data/bkk_transit_links.json")
    parser.add_argument("--out-shape-map", default="data/bkk_shape_link_map_transit.json")
    parser.add_argument("--out-trip-map", default="data/bkk_trip_shape_map.json")
    parser.add_argument("--out-route-map", default="data/bkk_route_shape_map.json")
    parser.add_argument("--link-id-prefix", default="gtfs_shape_")
    parser.add_argument("--default-capacity", type=int, default=4000)
    parser.add_argument("--default-price", type=int, default=250)
    parser.add_argument("--min-points", type=int, default=2)
    args = parser.parse_args()

    shape_points = defaultdict(list)
    trip_map = {}
    shape_route_counts = defaultdict(Counter)
    shape_headsign = {}
    route_info = {}

    with zipfile.ZipFile(args.gtfs_zip, "r") as zf:
        for row in load_csv(zf, "shapes.txt"):
            shape_id = row.get("shape_id")
            if not shape_id:
                continue
            seq = int(row.get("shape_pt_sequence") or 0)
            lat = float(row.get("shape_pt_lat") or 0)
            lon = float(row.get("shape_pt_lon") or 0)
            shape_points[shape_id].append((seq, lat, lon))

        for row in load_csv(zf, "trips.txt"):
            trip_id = row.get("trip_id")
            shape_id = row.get("shape_id")
            route_id = row.get("route_id")
            headsign = row.get("trip_headsign")
            if trip_id and shape_id:
                trip_map[trip_id] = shape_id
            if shape_id and route_id:
                shape_route_counts[shape_id][route_id] += 1
            if shape_id and headsign and shape_id not in shape_headsign:
                shape_headsign[shape_id] = headsign

        for row in load_csv(zf, "routes.txt"):
            route_id = row.get("route_id")
            if not route_id:
                continue
            route_info[route_id] = {
                "short_name": row.get("route_short_name") or "",
                "long_name": row.get("route_long_name") or "",
                "route_type": row.get("route_type") or "",
            }

    links = []
    shapes_out = {}
    total_points = 0
    skipped_shapes = 0

    for shape_id, points in shape_points.items():
        ordered = sorted(points, key=lambda p: p[0])
        if len(ordered) < args.min_points:
            skipped_shapes += 1
            continue

        route_id = pick_route_id(shape_route_counts.get(shape_id))
        route_meta = route_info.get(route_id, {})
        route_type = route_meta.get("route_type", "")
        mode_label, capacity, price = MODE_DEFAULTS.get(
            route_type,
            ("Transit", args.default_capacity, args.default_price),
        )

        short_name = ascii_or_empty(route_meta.get("short_name") or "")
        if not short_name:
            short_name = ascii_or_empty(route_id) or ascii_or_empty(shape_id)
        headsign = ascii_or_empty(shape_headsign.get(shape_id, ""))

        name_parts = [mode_label]
        if short_name:
            name_parts.append(short_name)
        if headsign:
            name_parts.append(headsign)
        name = " ".join(name_parts).strip() or f"Transit {shape_id}"

        link_id = f"{args.link_id_prefix}{shape_id}"
        coords = []
        points_out = []
        for _seq, lat, lon in ordered:
            coords.append([lat, lon])
            points_out.append([lat, lon, link_id])
        total_points += len(points_out)

        links.append({
            "id": link_id,
            "name": name,
            "capacity": capacity,
            "base_price_huf": price,
            "type": "transit",
            "coordinates": coords,
        })
        shapes_out[shape_id] = {
            "points": points_out,
            "link_ids": [link_id],
        }

    route_map = defaultdict(set)
    for shape_id, counter in shape_route_counts.items():
        for route_id in counter:
            route_map[route_id].add(shape_id)

    meta = {
        "created_at": time.time(),
        "shape_count": len(shapes_out),
        "skipped_shapes": skipped_shapes,
        "total_points": total_points,
    }

    Path(args.out_links).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_links, "w", encoding="utf-8") as handle:
        json.dump({"meta": meta, "links": links}, handle, separators=(",", ":"))

    Path(args.out_shape_map).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_shape_map, "w", encoding="utf-8") as handle:
        json.dump({"meta": meta, "shapes": shapes_out}, handle, separators=(",", ":"))

    with open(args.out_trip_map, "w", encoding="utf-8") as handle:
        json.dump(trip_map, handle, separators=(",", ":"))

    route_map_out = {route_id: sorted(list(shape_ids)) for route_id, shape_ids in route_map.items()}
    with open(args.out_route_map, "w", encoding="utf-8") as handle:
        json.dump(route_map_out, handle, separators=(",", ":"))

    print("links", len(links))
    print("shapes", len(shapes_out))
    print("points", total_points)
    print("trips", len(trip_map))
    print("routes", len(route_map_out))


if __name__ == "__main__":
    main()
