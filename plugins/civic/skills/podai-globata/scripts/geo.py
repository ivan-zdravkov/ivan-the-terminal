#!/usr/bin/env python3
"""Address, nearest intersection and recipients for a violation. Stdlib only.

  geo.py locate LAT LON [--green]           reverse-geocode (OpenStreetMap) + route
  geo.py route OBLAST [MUNICIPALITY] [--green]   recipients only (when offline or the user typed the place)

--green: the car is on a green area (lawn, park), which some cities route to a different inspectorate.
Needs network access to nominatim.openstreetmap.org (overpass-api.de optional). Without it, `locate`
prints {"error": ...} and exits 3: ask the user for the address and run `route`.
"""
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "podai-globata/1.0 (+https://github.com/ivan-zdravkov/ivan-the-terminal)"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
OVERPASS = "https://overpass-api.de/api/interpreter"
NOT_ROADS = "footway|path|cycleway|steps|corridor|track|bridleway|proposed|construction|platform"
DATA = Path(__file__).resolve().parent.parent / "references" / "authorities.json"


def fetch(url, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "bg"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def reverse(lat, lon, zoom=18):
    q = urllib.parse.urlencode({"format": "jsonv2", "lat": lat, "lon": lon, "zoom": zoom,
                                "addressdetails": 1, "accept-language": "bg"})
    return fetch(f"{NOMINATIM}?{q}").get("address", {})


def metres(la1, lo1, la2, lo2):
    la1, lo1, la2, lo2 = map(math.radians, (la1, lo1, la2, lo2))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def intersection(lat, lon, elements):
    """Nearest node shared by two differently named roads, from an Overpass 'out body; >; out skel' result."""
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in elements if e["type"] == "node"}
    names = {}
    for w in (e for e in elements if e["type"] == "way"):
        for n in w.get("nodes", []):
            names.setdefault(n, set()).add(w["tags"]["name"])
    best = None
    for n, ns in names.items():
        if len(ns) >= 2 and n in nodes:
            d = metres(lat, lon, *nodes[n])
            if best is None or d < best[0]:
                best = (d, sorted(ns))
    return {"streets": best[1][:2], "distance_m": round(best[0])} if best else None


def overpass(lat, lon, radius=60):
    q = (f'[out:json][timeout:12];way(around:{radius},{lat},{lon})[highway~"."][highway!~"^({NOT_ROADS})$"][name];'
         "out body;>;out skel qt;")
    return fetch(OVERPASS, urllib.parse.urlencode({"data": q}).encode(), timeout=20)["elements"]


def nearby_streets(lat, lon, main):
    """Fallback when Overpass is busy: probe ~35 m around the point for other street names."""
    found = []
    dlat, dlon = 35 / 111320, 35 / (111320 * math.cos(math.radians(lat)))
    for la, lo in ((lat + dlat, lon), (lat, lon + dlon), (lat - dlat, lon), (lat, lon - dlon)):
        time.sleep(1.1)  # Nominatim policy: at most one request per second
        try:
            road = reverse(la, lo, zoom=17).get("road")
        except OSError:
            break
        if road and road != main and road not in found:
            found.append(road)
    return found


def norm(s):
    s = (s or "").lower().replace("област", "").replace("община", "").replace("софийска", "софия")
    return s.strip(" -")


def pick(table, *keys):
    by = {norm(k): v for k, v in table.items()}
    return next((by[norm(k)] for k in keys if k and norm(k) in by), None)


def route(oblast, municipality=None, green=False, city=None):
    db = json.loads(DATA.read_text(encoding="utf-8"))
    if norm(municipality or city or oblast) in ("софия", "столична", "софия-град", "sofia"):
        oblast, municipality = "София-град", "Столична"  # "София" typed by a user means the city, not the province
    mvr = pick(db["mvr"], oblast)
    mun = pick(db["municipal"], municipality, city)
    grn = pick(db["green_area"], municipality, city) if green else None
    to, cc, lookup = [db["national"]], [], []
    if grn or mun:
        cc.append(grn or mun)
    else:
        lookup.append(f"municipal parking control for {municipality or city or oblast}: search the municipality's "
                      "site for its email for reports (сигнали) and add it as Cc; if none, the МВР reception alone is fine")
    for r in cc:
        if r.get("confidence") == "medium":
            lookup.append(f"verify {r['email']} ({r['name']}) if you can search the web")
    fallback = [mvr] if mvr and mvr.get("email") else []
    slim = lambda rs: [{k: r[k] for k in ("name", "email", "confidence") if k in r} for r in rs]  # noqa: E731
    return {"to": slim(to), "cc": slim(cc), "fallback": slim(fallback), "lookup": lookup}


def locate(lat, lon, green):
    out = {"maps_url": f"https://maps.google.com/?q={lat},{lon}"}
    try:
        a = reverse(lat, lon)
    except OSError as e:
        return out | {"error": f"no network to OpenStreetMap ({e.__class__.__name__})",
                      "next": "ask for the street and city, then: geo.py route OBLAST MUNICIPALITY"}, 3
    city = a.get("city") or a.get("town") or a.get("village")
    out["address"] = {k: a.get(k) for k in ("road", "house_number", "suburb", "postcode") if a.get(k)}
    out["address"] |= {"city": city, "municipality": a.get("state_district") or a.get("municipality"),
                       "oblast": a.get("state")}
    if a.get("country_code") not in (None, "bg"):
        out["warning"] = "outside Bulgaria: this skill only knows Bulgarian authorities"
    try:
        out["intersection"] = intersection(lat, lon, overpass(lat, lon))
    except (OSError, KeyError, ValueError):
        out["near_streets"] = nearby_streets(lat, lon, a.get("road"))
    out["recipients"] = route(a.get("state"), out["address"]["municipality"], green, city)
    return out, 0


def main(argv):
    green = "--green" in argv
    args = [a for a in argv if a != "--green"]
    if len(args) == 3 and args[0] == "locate":
        try:
            lat, lon = float(args[1]), float(args[2])
        except ValueError:
            return usage()
        res, code = locate(lat, lon, green)
    elif args[:1] == ["route"] and 2 <= len(args) <= 3:
        res, code = route(args[1], args[2] if len(args) == 3 else None, green, args[1]), 0
    else:
        return usage()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return code


def usage():
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
