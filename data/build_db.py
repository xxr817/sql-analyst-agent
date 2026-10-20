"""Build the demo SQLite database used by the agent.

IMPORTANT: All registration figures and prices are SYNTHETIC demo data generated
with a fixed random seed. Brand and model names are used only to make the data
readable; the numbers do NOT reflect real KBA registration statistics.

Usage:
    python data/build_db.py            # writes data/autos.db
"""
from __future__ import annotations

import math
import random
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("autos.db")
SEED = 42

BRANDS = [
    # name, country, group
    ("BMW", "Deutschland", "BMW Group"),
    ("Mercedes-Benz", "Deutschland", "Mercedes-Benz Group"),
    ("Volkswagen", "Deutschland", "Volkswagen AG"),
    ("Audi", "Deutschland", "Volkswagen AG"),
    ("Tesla", "USA", "Tesla"),
    ("BYD", "China", "BYD"),
    ("Hyundai", "Südkorea", "Hyundai Motor Group"),
    ("Skoda", "Tschechien", "Volkswagen AG"),
    ("Renault", "Frankreich", "Renault Group"),
    ("MG", "China", "SAIC Motor"),
]

# brand, model, segment, powertrain, base_price_eur, base_monthly_volume
MODELS = [
    ("BMW", "i4", "Mittelklasse", "BEV", 57900, 900),
    ("BMW", "iX1", "SUV", "BEV", 48900, 1100),
    ("BMW", "3er", "Mittelklasse", "ICE", 45500, 2600),
    ("BMW", "X3", "SUV", "PHEV", 64900, 1300),
    ("Mercedes-Benz", "EQA", "SUV", "BEV", 50900, 800),
    ("Mercedes-Benz", "C-Klasse", "Mittelklasse", "ICE", 49800, 2400),
    ("Mercedes-Benz", "GLC", "SUV", "PHEV", 66700, 1500),
    ("Volkswagen", "ID.3", "Kompaktklasse", "BEV", 36900, 1600),
    ("Volkswagen", "ID.4", "SUV", "BEV", 42900, 1700),
    ("Volkswagen", "Golf", "Kompaktklasse", "ICE", 29600, 5200),
    ("Volkswagen", "Tiguan", "SUV", "PHEV", 46500, 3000),
    ("Audi", "Q4 e-tron", "SUV", "BEV", 51900, 1200),
    ("Audi", "A4", "Mittelklasse", "ICE", 44600, 2000),
    ("Tesla", "Model 3", "Mittelklasse", "BEV", 40900, 1300),
    ("Tesla", "Model Y", "SUV", "BEV", 44900, 2600),
    ("BYD", "Atto 3", "SUV", "BEV", 37990, 250),
    ("BYD", "Dolphin", "Kompaktklasse", "BEV", 32990, 200),
    ("BYD", "Seal", "Mittelklasse", "BEV", 44990, 120),
    ("Hyundai", "Ioniq 5", "SUV", "BEV", 43900, 700),
    ("Hyundai", "Tucson", "SUV", "PHEV", 37500, 1400),
    ("Skoda", "Enyaq", "SUV", "BEV", 44900, 1500),
    ("Skoda", "Octavia", "Kompaktklasse", "ICE", 31200, 3600),
    ("Renault", "Megane E-Tech", "Kompaktklasse", "BEV", 39900, 400),
    ("Renault", "Clio", "Kleinwagen", "ICE", 18900, 1600),
    ("MG", "MG4", "Kompaktklasse", "BEV", 34990, 700),
    ("MG", "ZS", "SUV", "ICE", 21990, 500),
]

# Bundesland, rough population weight
STATES = [
    ("Baden-Württemberg", 11.3), ("Bayern", 13.4), ("Berlin", 3.8),
    ("Brandenburg", 2.6), ("Bremen", 0.7), ("Hamburg", 1.9), ("Hessen", 6.4),
    ("Mecklenburg-Vorpommern", 1.6), ("Niedersachsen", 8.1),
    ("Nordrhein-Westfalen", 18.1), ("Rheinland-Pfalz", 4.2), ("Saarland", 1.0),
    ("Sachsen", 4.1), ("Sachsen-Anhalt", 2.2), ("Schleswig-Holstein", 3.0),
    ("Thüringen", 2.1),
]

MONTHS = [f"{y}-{m:02d}" for y in (2023, 2024, 2025) for m in range(1, 13)]

SCHEMA = """
CREATE TABLE brands (
    brand_id    INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    country     TEXT NOT NULL,          -- Herkunftsland der Marke
    group_name  TEXT NOT NULL           -- Konzern
);
CREATE TABLE models (
    model_id        INTEGER PRIMARY KEY,
    brand_id        INTEGER NOT NULL REFERENCES brands(brand_id),
    name            TEXT NOT NULL,
    segment         TEXT NOT NULL,      -- Kleinwagen, Kompaktklasse, Mittelklasse, SUV
    powertrain      TEXT NOT NULL,      -- BEV (elektrisch), PHEV (Plug-in-Hybrid), ICE (Verbrenner)
    base_price_eur  INTEGER NOT NULL    -- Grundpreis in Euro
);
CREATE TABLE registrations (
    registration_id INTEGER PRIMARY KEY,
    model_id        INTEGER NOT NULL REFERENCES models(model_id),
    month           TEXT NOT NULL,      -- Format YYYY-MM
    state           TEXT NOT NULL,      -- Bundesland
    units           INTEGER NOT NULL    -- Neuzulassungen (synthetisch)
);
CREATE INDEX idx_reg_month ON registrations(month);
CREATE INDEX idx_reg_model ON registrations(model_id);
"""


def growth_factor(brand: str, powertrain: str, month_index: int) -> float:
    """Trend over 36 months: BEV grows, ICE shrinks, Chinese brands grow fastest."""
    t = month_index / 35
    factor = 1.0
    if powertrain == "BEV":
        factor *= 1 + 0.45 * t
    elif powertrain == "ICE":
        factor *= 1 - 0.30 * t
    if brand in ("BYD", "MG"):
        factor *= 1 + 1.2 * t
    if brand == "Tesla":
        factor *= 1 - 0.35 * t
    season = 1 + 0.12 * math.sin(2 * math.pi * (month_index % 12) / 12)
    return factor * season


def build(db_path: Path = DB_PATH) -> Path:
    rng = random.Random(SEED)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    brand_ids = {}
    for i, (name, country, group) in enumerate(BRANDS, start=1):
        con.execute("INSERT INTO brands VALUES (?,?,?,?)", (i, name, country, group))
        brand_ids[name] = i

    rows = []
    total_weight = sum(w for _, w in STATES)
    for model_id, (brand, model, segment, pt, price, vol) in enumerate(MODELS, start=1):
        con.execute(
            "INSERT INTO models VALUES (?,?,?,?,?,?)",
            (model_id, brand_ids[brand], model, segment, pt, price),
        )
        for mi, month in enumerate(MONTHS):
            monthly = vol * growth_factor(brand, pt, mi)
            for state, weight in STATES:
                bias = 1.25 if (brand == "BMW" and state == "Bayern") else 1.0
                expected = monthly * weight / total_weight * bias
                units = max(0, int(round(expected * rng.uniform(0.8, 1.2))))
                rows.append((model_id, month, state, units))

    con.executemany(
        "INSERT INTO registrations (model_id, month, state, units) VALUES (?,?,?,?)", rows
    )
    con.commit()
    con.close()
    return db_path


if __name__ == "__main__":
    path = build()
    print(f"Datenbank erstellt: {path}")
