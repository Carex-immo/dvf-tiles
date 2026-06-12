#!/usr/bin/env python3
"""Réplique Python de la consolidation DVF de l'app iOS (lot P1).

Source de vérité : le code Swift —
  - parseGeoDvfCSV / parseCSVLine   (carex.immo/Services/DVFService+Parsing.swift)
  - consolidateMutations            (idem)
  - init de commodité de Mutation   (carex.immo/Models/Mutation.swift)
  - computePrimaryType (post-P0, tie-break déterministe)
  - PropertyType.classify / MutationType.classify / priorityOrder
                                    (carex.immo/Models/Mutation+Classification.swift)

La parité est verrouillée par les golden-masters générés par le test Swift
`GeoDvfGoldenTests` (tools/dvf-tiles/tests/goldens/) et rejoués par
tests/test_parity.py. Toute divergence de règle ici fausserait les compteurs
de la couche `dots` au dézoom — ne JAMAIS « corriger » une règle de ce
fichier sans changer le Swift et régénérer les goldens.

Divergence assumée vs le parser Swift (documentée au plan) : une ligne qui
n'a pas exactement 40 champs est ignorée + comptée (`malformed_lines`) — le
Swift, header-indexé, tolérerait une ligne courte si les champs requis sont
présents. Les sources Etalab garantissent 40 colonnes (garde d'en-tête P4).

Cœur stdlib uniquement (csv, json, math) — pas de dépendance tierce.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Schéma source (geo-dvf, 40 colonnes)

EXPECTED_FIELD_COUNT = 40

HEADER = [
    "id_mutation", "date_mutation", "numero_disposition", "nature_mutation",
    "valeur_fonciere", "adresse_numero", "adresse_suffixe", "adresse_nom_voie",
    "adresse_code_voie", "code_postal", "code_commune", "nom_commune",
    "code_departement", "ancien_code_commune", "ancien_nom_commune",
    "id_parcelle", "ancien_id_parcelle", "numero_volume",
    "lot1_numero", "lot1_surface_carrez", "lot2_numero", "lot2_surface_carrez",
    "lot3_numero", "lot3_surface_carrez", "lot4_numero", "lot4_surface_carrez",
    "lot5_numero", "lot5_surface_carrez", "nombre_lots", "code_type_local",
    "type_local", "surface_reelle_bati", "nombre_pieces_principales",
    "code_nature_culture", "nature_culture", "code_nature_culture_speciale",
    "nature_culture_speciale", "surface_terrain", "longitude", "latitude",
]

LOT_CARREZ_COLUMNS = [f"lot{i}_surface_carrez" for i in range(1, 6)]

# ---------------------------------------------------------------------------
# Primitives numériques — alignées sur Swift

def fold_sum(values) -> float:
    """Somme par fold naïf gauche→droite — réplique Swift `reduce(0, +)`.

    PAS le `sum()` builtin : depuis Python 3.12 il applique la sommation
    compensée de Neumaier sur les floats et peut différer d'1 ulp du fold
    Swift (vu sur les sommes Carrez : 3.55+12.97+12.24).
    """
    acc = 0.0
    for v in values:
        acc += v
    return acc


def round_half_away(x: float) -> int:
    """Réplique de Swift `.rounded()` (half-away-from-zero).

    PAS `round()` Python, qui arrondit au pair (banker's rounding).
    """
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


def round5(x: float) -> float:
    """Coordonnée à 5 décimales, half-away — réplique `(x*1e5).rounded()/1e5`."""
    return round_half_away(x * 1e5) / 1e5


def parse_float(s: str | None) -> float | None:
    """Réplique `Double(_:)` sur champ vide → nil.

    Divergence assumée : inf/nan (jamais émis par Etalab) → None plutôt
    qu'un crash d'arrondi en aval — Swift trapperait pareillement sur
    `Int(inf)`, aucun golden ne peut donc exister pour ces valeurs.
    """
    if not s:
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_int(s: str | None) -> int | None:
    """Réplique du helper Swift : Int(s) sinon Int(exactly: Double(s).rounded())
    si fini (inf/nan → nil, jamais d'exception)."""
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        d = float(s)
    except ValueError:
        return None
    if not math.isfinite(d):
        return None
    return round_half_away(d)


# ---------------------------------------------------------------------------
# Classification — réplique de Mutation+Classification.swift

PRIORITY_ORDER = ["immeuble", "maison", "appartement", "local", "dependance"]

# Codes de la couche `dots` = ordre de déclaration des enums Swift.
PROPERTY_TYPE_CODE = {"maison": 1, "appartement": 2, "immeuble": 3,
                      "local": 4, "dependance": 5}
MUTATION_TYPE_CODE = {"vente": 1, "vefa": 2, "adjudication": 3,
                      "echange": 4, "expropriation": 5}


def classify_property_type(type_local: str | None) -> str | None:
    """Réplique `PropertyType.classify` (substrings, même ordre, jamais immeuble)."""
    if not type_local:
        return None
    if "Maison" in type_local:
        return "maison"
    if "Appartement" in type_local:
        return "appartement"
    if "Dépendance" in type_local:
        return "dependance"
    if "Local" in type_local:
        return "local"
    return None


def classify_mutation_type(nature: str | None) -> str:
    """Réplique `MutationType.classify` (nil → vente)."""
    if not nature:
        return "vente"
    if "futur" in nature:
        return "vefa"
    if "Adjudication" in nature:
        return "adjudication"
    if "change" in nature:
        return "echange"
    if "Expropriation" in nature:
        return "expropriation"
    return "vente"


def compute_primary_type(counts: dict[str, int],
                         surface_by_type: dict[str, float]) -> str | None:
    """Réplique `Mutation.computePrimaryType` (post-P0, déterministe)."""
    nb_appart = counts.get("appartement", 0)
    nb_local = counts.get("local", 0)
    if nb_appart >= 3 or (nb_appart >= 1 and nb_local >= 1):
        return "immeuble"
    winner: tuple[str, float] | None = None
    for ptype in PRIORITY_ORDER:
        if ptype == "dependance":
            continue
        surface = surface_by_type.get(ptype)
        if surface is None or surface <= 0:
            continue
        if winner is None or surface > winner[1]:
            winner = (ptype, surface)
    if winner is not None:
        return winner[0]
    present = set(counts)
    for ptype in PRIORITY_ORDER:
        if ptype in present and ptype != "dependance":
            return ptype
    for ptype in PRIORITY_ORDER:
        if ptype in present:
            return ptype
    return None


# ---------------------------------------------------------------------------
# Lecture + groupes contigus

@dataclass
class Stats:
    rows_read: int = 0
    malformed_lines: int = 0
    skipped_rows: int = 0            # champs requis absents (id/parcelle/date)
    contiguity_violated: bool = False
    rejected_mutations: int = 0      # parcelle d'ancrage sans coordonnée
    embedded_no_coord_rows: int = 0  # lignes sans coords de mutations CONSERVÉES


@dataclass
class Result:
    mutations: list[dict] = field(default_factory=list)   # schéma du golden, trié par id
    rejected_ids: list[str] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)


def read_rows(path: str, stats: Stats) -> list[dict]:
    """Lit le CSV : assertion 40 champs (sinon `malformed_lines`), champs
    requis non vides (sinon `skipped_rows`), champs vides → None."""
    rows: list[dict] = []
    # utf-8-sig : strippe un éventuel BOM (Swift String(data:) le strippe
    # aussi — sans ça, "\ufeffid_mutation" raterait l'index d'en-tête et le
    # fichier parserait silencieusement à zéro ligne).
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return rows
        index = {name.strip(): i for i, name in enumerate(header)}
        required = ("id_mutation", "id_parcelle", "date_mutation")
        missing = [name for name in required if name not in index]
        if missing:
            # Pipeline de build : une dérive d'en-tête doit échouer FORT
            # (divergence assumée avec le parser Swift, qui renvoie vide).
            raise ValueError(f"en-tête invalide — colonnes requises absentes : {missing}")
        for fields_ in reader:
            stats.rows_read += 1
            if len(fields_) != EXPECTED_FIELD_COUNT:
                stats.malformed_lines += 1
                continue

            def get(name: str) -> str | None:
                i = index.get(name)
                if i is None or i >= len(fields_) or fields_[i] == "":
                    return None
                return fields_[i]

            if any(get(name) is None for name in required):
                stats.skipped_rows += 1
                continue
            carrez_values = [parse_float(get(c)) for c in LOT_CARREZ_COLUMNS]
            carrez_present = [v for v in carrez_values if v is not None]
            rows.append({
                "id_mutation": get("id_mutation"),
                "id_parcelle": get("id_parcelle"),
                "date_mutation": get("date_mutation"),
                "nature_mutation": get("nature_mutation"),
                "valeur_fonciere": parse_float(get("valeur_fonciere")),
                "type_local": get("type_local"),
                "surface_reelle_bati": parse_float(get("surface_reelle_bati")),
                "nombre_pieces_principales": parse_int(get("nombre_pieces_principales")),
                "surface_terrain": parse_float(get("surface_terrain")),
                "surface_carrez": fold_sum(carrez_present) if carrez_present else None,
                "longitude": parse_float(get("longitude")),
                "latitude": parse_float(get("latitude")),
            })
    return rows


def build_coords_map(rows: list[dict]) -> dict[str, tuple[float, float]]:
    """Map globale parcelle → (lon, lat), première occurrence AVEC coordonnées
    — réplique du dictionnaire `centroids` de parseGeoDvfCSV (une mutation
    peut être ancrée par la ligne d'une autre mutation, même parcelle)."""
    coords: dict[str, tuple[float, float]] = {}
    for r in rows:
        pid = r["id_parcelle"]
        if pid in coords:
            continue
        lon, lat = r["longitude"], r["latitude"]
        if lon is not None and lat is not None:
            coords[pid] = (lon, lat)
    return coords


def contiguous_groups(rows: list[dict], stats: Stats) -> list[list[dict]]:
    """Groupes par id_mutation, ordre du fichier. Si les lignes d'une mutation
    ne sont pas contiguës : tri stable de secours par id_mutation (l'ordre
    interne de chaque mutation est préservé), puis regroupement — résultat
    identique au fichier contigu équivalent."""
    def split(seq: list[dict]) -> tuple[list[list[dict]], bool]:
        groups: list[list[dict]] = []
        seen: set[str] = set()
        current_id: str | None = None
        for r in seq:
            rid = r["id_mutation"]
            if rid != current_id:
                if rid in seen:
                    return groups, True   # violation de contiguïté
                seen.add(rid)
                current_id = rid
                groups.append([])
            groups[-1].append(r)
        return groups, False

    groups, violated = split(rows)
    if not violated:
        return groups
    stats.contiguity_violated = True
    groups, violated = split(sorted(rows, key=lambda r: r["id_mutation"]))
    assert not violated
    return groups


# ---------------------------------------------------------------------------
# Consolidation — réplique de consolidateMutations + init de commodité

def consolidate_group(rows: list[dict],
                      coords: dict[str, tuple[float, float]]) -> dict | None:
    """Une mutation consolidée (schéma du golden), ou None si rejetée
    (parcelle de la 1ʳᵉ ligne sans coordonnée — aucun repli)."""
    first = rows[0]
    anchor = coords.get(first["id_parcelle"])
    if anchor is None:
        return None

    # Biens bruts : seules les lignes à type_local non vide (les lignes
    # terrain-nu n'alimentent que les parcelles).
    raw_biens = [
        {"type": r["type_local"],
         "surf_bati": r["surface_reelle_bati"],
         "pieces": r["nombre_pieces_principales"],
         "surf_terrain": r["surface_terrain"],
         "carrez": r["surface_carrez"]}
        for r in rows if r["type_local"] is not None
    ]

    # Fusion : même clé (type brut, bâti, pièces, Carrez — nil en sentinelle)
    # ET ≥ 2 valeurs distinctes de terrain (nil ≡ 0) → UN bien, attributs du
    # premier, terrain = Σ des terrains non-nil (0 → nil).
    group_order: list[tuple] = []
    groups: dict[tuple, list[dict]] = {}
    for b in raw_biens:
        key = (b["type"],
               b["surf_bati"] if b["surf_bati"] is not None else -1.0,
               b["pieces"] if b["pieces"] is not None else -1,
               b["carrez"] if b["carrez"] is not None else -1.0)
        if key not in groups:
            group_order.append(key)
            groups[key] = []
        groups[key].append(b)
    biens: list[dict] = []
    for key in group_order:
        group = groups[key]
        terrains = {b["surf_terrain"] if b["surf_terrain"] is not None else 0.0
                    for b in group}
        if len(group) > 1 and len(terrains) > 1:
            total_terrain = fold_sum(b["surf_terrain"] for b in group
                                     if b["surf_terrain"] is not None)
            fused = dict(group[0])
            fused["surf_terrain"] = total_terrain if total_terrain > 0 else None
            biens.append(fused)
        else:
            biens.extend(group)

    # Agrégats (réplique de l'init de commodité — une passe sur les biens).
    # Ordre de fold : Swift somme sur les biens TRIÉS par priorité (tri non
    # stable, ordre des égalités non spécifié) ; ici ordre de découverte.
    # Risque résiduel d'1 ulp si des surfaces fractionnaires se mélangeaient
    # entre types — les surfaces geo-dvf sont entières (exactes dans tout
    # ordre), divergence impossible sur données conformes.
    surface_batie = 0.0
    surface_terrain_biens = 0.0
    pieces_total = 0
    counts: dict[str, int] = {}
    surface_by_type: dict[str, float] = {}
    for b in biens:
        cls = classify_property_type(b["type"])
        if cls is not None:
            counts[cls] = counts.get(cls, 0) + 1
            surface_by_type[cls] = surface_by_type.get(cls, 0.0) + (b["surf_bati"] or 0.0)
        if cls != "dependance" and b["surf_bati"] is not None:
            surface_batie += b["surf_bati"]
        if b["surf_terrain"] is not None:
            surface_terrain_biens += b["surf_terrain"]
        if b["pieces"] is not None:
            pieces_total += b["pieces"]

    # Parcelles : max de (surface_terrain ?? 0) par parcelle sur TOUTES les
    # lignes ; total terrain = Σ parcelles si > 0, sinon Σ terrains des biens.
    parcelle_max: dict[str, float] = {}
    for r in rows:
        pid = r["id_parcelle"]
        surf = r["surface_terrain"] if r["surface_terrain"] is not None else 0.0
        if surf > parcelle_max.get(pid, -1.0):
            parcelle_max[pid] = surf
    # Swift somme `parcelles` APRÈS tri par surface décroissante — l'ordre
    # du fold naïf compte à l'ulp près (les égalités de surface sont sans
    # effet : permuter des valeurs égales ne change pas les sommes partielles).
    terrain_parcelles = fold_sum(sorted(parcelle_max.values(), reverse=True))
    surface_terrain = terrain_parcelles if terrain_parcelles > 0 else surface_terrain_biens

    primary = compute_primary_type(counts, surface_by_type)
    nature = classify_mutation_type(first["nature_mutation"])
    lon, lat = anchor

    return {
        "id": first["id_mutation"],
        "lat": round5(lat),
        "lon": round5(lon),
        "type": PROPERTY_TYPE_CODE[primary] if primary is not None else None,
        "nature": MUTATION_TYPE_CODE[nature],
        "prix": (round_half_away(first["valeur_fonciere"])
                 if first["valeur_fonciere"] is not None else None),
        "date": first["date_mutation"],
        "surfBati": round_half_away(surface_batie),
        "surfTerrain": round_half_away(surface_terrain),
        "pieces": pieces_total,
        "biens": _normalized_biens(biens),
    }


def _bien_sort_key(b: dict) -> tuple:
    """Tri canonique des biens — miroir exact du `sortKey` du test Swift."""
    cls = classify_property_type(b["type"])
    priority = PRIORITY_ORDER.index(cls) if cls is not None else len(PRIORITY_ORDER) + 100
    return (priority,
            b["type"],
            b["surf_bati"] if b["surf_bati"] is not None else -1.0,
            float(b["pieces"]) if b["pieces"] is not None else -1.0,
            b["surf_terrain"] if b["surf_terrain"] is not None else -1.0,
            b["carrez"] if b["carrez"] is not None else -1.0)


def _normalized_biens(biens: list[dict]) -> list[dict]:
    out = []
    for b in sorted(biens, key=_bien_sort_key):
        entry: dict = {"type": b["type"]}
        if b["surf_bati"] is not None:
            entry["surfBati"] = b["surf_bati"]
        if b["pieces"] is not None:
            entry["pieces"] = b["pieces"]
        if b["surf_terrain"] is not None:
            entry["surfTerrain"] = b["surf_terrain"]
        if b["carrez"] is not None:
            entry["surfCarrez"] = b["carrez"]
        out.append(entry)
    return out


def consolidate_file(path: str) -> Result:
    """Pipeline complet sur un CSV geo-dvf : lecture → map de coordonnées →
    groupes contigus → consolidation. Mutations triées par id (ordre du
    golden) ; rejets et compteurs dans `stats`."""
    result = Result()
    rows = read_rows(path, result.stats)
    coords = build_coords_map(rows)
    for group in contiguous_groups(rows, result.stats):
        mutation = consolidate_group(group, coords)
        if mutation is None:
            result.stats.rejected_mutations += 1
            result.rejected_ids.append(group[0]["id_mutation"])
            continue
        result.stats.embedded_no_coord_rows += sum(
            1 for r in group if r["longitude"] is None or r["latitude"] is None
        )
        result.mutations.append(mutation)
    result.mutations.sort(key=lambda m: m["id"])
    result.rejected_ids.sort()
    return result
