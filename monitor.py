#!/usr/bin/env python3
"""Veille des abonnements EFFIA - gare Le Creusot - Montceau TGV.

Interroge l'API utilisee par effia.com pour afficher les places d'abonnement
restantes, et envoie une notification push (ntfy.sh) des qu'une place se libere.

Logique reprise du site : places <= 0 -> "Plus d'abonnement disponible".

Variables d'environnement :
  NTFY_TOPIC         sujet ntfy secret (obligatoire pour recevoir les alertes)
  NTFY_SERVER        serveur ntfy (defaut : https://ntfy.sh)
  HEARTBEAT          "true" -> envoie aussi un message "veille active" si tout est complet
  TEST_NOTIFICATION  "true" -> envoie une notification de test puis continue
  EFFIA_API_BASE     base de l'API (defaut : https://www.effia.com), utile pour les tests
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date

# Parkings surveilles : (nom, id parking EFFIA, code produit abonnement, prix, page)
# Retire une ligne pour ne plus surveiller un parking.
PARKINGS = [
    ("P3", "0000400802", "20", "64 EUR/mois",
     "https://www.effia.com/parking/parking-gare-le-creusot-montceau-tgv-p3-effia#subscribe"),
    ("P2", "0000300802", "20", "64 EUR/mois",
     "https://www.effia.com/parking/parking-gare-le-creusot-montceau-tgv-p2-effia#subscribe"),
    ("P0 Premium", "0000100802", "5", "74 EUR/mois",
     "https://www.effia.com/parking/parking-gare-le-creusot-montceau-tgv-p0-effia#subscribe"),
]
VEHICLE = "AUTO"
MONTHS_AHEAD = 2  # mois de debut testes : M+1 et M+2 (comme le formulaire du site)

API_BASE = os.environ.get("EFFIA_API_BASE", "https://www.effia.com").rstrip("/")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
}


def start_months(n):
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m += 1
        if m > 12:
            m, y = 1, y + 1
        out.append(f"{y}-{m:02d}")
    return out


def get_availability(carpark_id, code, month):
    url = f"{API_BASE}/rest/subscription/availability/{carpark_id}/{VEHICLE}/{code}/{month}?_format=json"
    last_err = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
            if "places" not in data:
                raise ValueError(f"reponse inattendue : {data}")
            return data
        except (urllib.error.URLError, ValueError, json.JSONDecodeError, TimeoutError) as e:
            last_err = e
            time.sleep(3)
    raise RuntimeError(f"{url} -> {last_err}")


def notify(title, message, priority=3, click=None):
    if not NTFY_TOPIC:
        print("[ntfy] NTFY_TOPIC absent, notification non envoyee :", title)
        return
    payload = {"topic": NTFY_TOPIC, "title": title, "message": message, "priority": priority}
    if click:
        payload["click"] = click
        payload["actions"] = [{"action": "view", "label": "S'abonner", "url": click}]
    req = urllib.request.Request(
        NTFY_SERVER + "/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"[ntfy] envoye ({r.status}) : {title}")


def stats_line():
    total = os.environ.get("RUNS_24H", "").strip()
    failed = os.environ.get("FAILED_24H", "").strip()
    if not total or total == "?":
        return ""
    if failed and failed not in ("0", "?"):
        return f"{total} vérifications en 24h, dont {failed} en erreur.\n"
    return f"{total} vérifications en 24h, aucune erreur.\n"


def main():
    if os.environ.get("TEST_NOTIFICATION", "").lower() == "true":
        notify("Test veille EFFIA", "Les notifications fonctionnent.", priority=3,
               click=PARKINGS[0][4])

    months = start_months(MONTHS_AHEAD)
    hits, status, errors = [], [], []

    for name, carpark_id, code, price, page in PARKINGS:
        best, ok = None, 0
        for month in months:
            try:
                data = get_availability(carpark_id, code, month)
                ok += 1
            except RuntimeError as e:
                errors.append(f"{name} {month} : {e}")
                continue
            if data.get("available") is False:
                continue
            places = int(data.get("places") or 0)
            print(f"{name} debut {month} : places={places}")
            if places > 0 and (best is None or places > best[1]):
                best = (month, places)
        if best:
            hits.append((name, price, page, best[0], best[1]))
            status.append(f"{name}: {best[1]} place(s)")
        elif ok:
            status.append(f"{name}: complet")
        else:
            status.append(f"{name}: erreur")

    if hits:
        lines = [f"{n} ({p}) : {pl} place(s), debut {m}" for n, p, _, m, pl in hits]
        notify(
            "Place d'abonnement EFFIA disponible",
            "\n".join(lines) + "\nAbonne-toi vite sur effia.com.",
            priority=5,
            click=hits[0][2],
        )
    elif os.environ.get("HEARTBEAT", "").lower() == "true":
        notify("Veille EFFIA active", stats_line() + " | ".join(status),
               priority=2)

    print("Resultat :", " | ".join(status))
    if errors:
        print("ERREURS :\n" + "\n".join(errors), file=sys.stderr)
        sys.exit(1)  # le run echoue -> GitHub t'envoie un email


if __name__ == "__main__":
    main()
