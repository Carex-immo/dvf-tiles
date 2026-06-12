#!/usr/bin/env python3
"""Génère les fixtures synthétiques du harnais de parité (lot P1).

Sorties (committées, ré-exécutable de manière déterministe) :
  - synthetic.csv             : cas construits S-01…S-11 + 1 ligne invalide
  - synthetic-desordonne.csv  : mêmes lignes, mutations S-05/S-06/S-09
    entrelacées (ordre interne de chaque mutation préservé) — teste le
    tri de secours de l'assertion de contiguïté.

Cas couverts (cf. plan 2026-06-11-tuiles-P1-consolidation-parite.md) :
  S-01 mutation mixte (ligne sans coords embarquée + terrain nu)
  S-02 rejetée (parcelle de la 1ʳᵉ ligne sans coordonnée nulle part)
  S-03 ancrée via la parcelle d'une AUTRE mutation (map globale)
  S-04 porteuse des coordonnées de la parcelle partagée avec S-03
  S-05 fusion de biens (terrains distincts) — surfTerrain par parcelle (max)
       diverge volontairement du terrain du bien fusionné (somme)
  S-06 non-fusion (2 biens identiques, terrains tous absents)
  S-07 égalité de cumul maison/local → tie-break priorityOrder (P0)
  S-08 dépendance seule
  S-09 immeuble (3 appartements)
  S-10 terrain nu seul (primaryType nil, conservée)
  S-11 arrondi du prix (118750.49) + nature VEFA
"""
import csv
import os

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

ROWS = []  # liste de (id_groupe, ligne)


def add(gid, **kw):
    assert set(kw) <= set(HEADER), sorted(set(kw) - set(HEADER))
    base = {k: "" for k in HEADER}
    base.update(kw)
    ROWS.append((gid, [base[k] for k in HEADER]))


def common(gid, parcelle, **kw):
    d = dict(id_mutation=gid, date_mutation="2024-03-15", nature_mutation="Vente",
             code_postal="73000", nom_commune="Synthville", code_commune="73999",
             code_departement="73", id_parcelle=parcelle)
    d.update(kw)
    return d


# S-01 — mixte : maison géolocalisée + dépendance sans coords + terrain nu.
add("S-01", **common("S-01", "SYN0000000001", valeur_fonciere="250000",
                     type_local="Maison", surface_reelle_bati="100",
                     nombre_pieces_principales="4", surface_terrain="500",
                     longitude="5.900012", latitude="45.500016"))
add("S-01", **common("S-01", "SYN0000000002", valeur_fonciere="250000",
                     type_local="Dépendance"))
add("S-01", **common("S-01", "SYN0000000003", valeur_fonciere="250000",
                     nature_culture="terres", surface_terrain="350"))

# S-02 — rejetée : la parcelle de la 1ʳᵉ ligne n'a de coords nulle part,
# même si la 2ᵉ ligne est géolocalisée.
add("S-02", **common("S-02", "SYN0000000010", valeur_fonciere="90000",
                     type_local="Maison", surface_reelle_bati="60",
                     nombre_pieces_principales="3"))
add("S-02", **common("S-02", "SYN0000000011", valeur_fonciere="90000",
                     type_local="Dépendance",
                     longitude="5.910000", latitude="45.510000"))

# S-03 — sans coords sur SA ligne ; la parcelle SYN0000000020 est
# géolocalisée par une ligne de S-04 (map globale parcelle → coords).
add("S-03", **common("S-03", "SYN0000000020", valeur_fonciere="150000",
                     type_local="Appartement", surface_reelle_bati="50",
                     nombre_pieces_principales="2"))

# S-04 — porte les coordonnées de la parcelle partagée.
add("S-04", **common("S-04", "SYN0000000020", valeur_fonciere="200000",
                     type_local="Maison", surface_reelle_bati="80",
                     nombre_pieces_principales="3",
                     longitude="5.920000", latitude="45.520000"))

# S-05 — fusion : même clé (type/surf/pièces/Carrez), terrains 120 ≠ 250
# → UN bien (terrain 370) ; parcelle unique → surfTerrain total = max = 250.
add("S-05", **common("S-05", "SYN0000000050", valeur_fonciere="300000",
                     type_local="Appartement", surface_reelle_bati="37",
                     nombre_pieces_principales="1",
                     lot1_numero="15", lot1_surface_carrez="31.57",
                     surface_terrain="120",
                     longitude="5.930000", latitude="45.530000"))
add("S-05", **common("S-05", "SYN0000000050", valeur_fonciere="300000",
                     type_local="Appartement", surface_reelle_bati="37",
                     nombre_pieces_principales="1",
                     lot1_numero="15", lot1_surface_carrez="31.57",
                     surface_terrain="250",
                     longitude="5.930000", latitude="45.530000"))

# S-06 — non-fusion : 2 biens identiques, terrains tous absents ({0}).
for _ in range(2):
    add("S-06", **common("S-06", "SYN0000000060", valeur_fonciere="180000",
                         type_local="Appartement", surface_reelle_bati="42",
                         nombre_pieces_principales="2",
                         longitude="5.940000", latitude="45.540000"))

# S-07 — égalité de cumul (100 vs 100) → maison (tie-break priorityOrder).
add("S-07", **common("S-07", "SYN0000000070", valeur_fonciere="400000",
                     type_local="Local industriel. commercial ou assimilé",
                     surface_reelle_bati="100",
                     longitude="5.950000", latitude="45.550000"))
add("S-07", **common("S-07", "SYN0000000070", valeur_fonciere="400000",
                     type_local="Maison", surface_reelle_bati="100",
                     nombre_pieces_principales="4",
                     longitude="5.950000", latitude="45.550000"))

# S-08 — dépendance seule.
add("S-08", **common("S-08", "SYN0000000080", valeur_fonciere="15000",
                     type_local="Dépendance", surface_reelle_bati="20",
                     longitude="5.960000", latitude="45.560000"))

# S-09 — immeuble de rendement (3 appartements).
for surf, pieces in (("30", "1"), ("35", "2"), ("40", "2")):
    add("S-09", **common("S-09", "SYN0000000090", valeur_fonciere="500000",
                         type_local="Appartement", surface_reelle_bati=surf,
                         nombre_pieces_principales=pieces,
                         longitude="5.970000", latitude="45.570000"))

# S-10 — terrain nu seul : aucun bien → primaryType nil, conservée.
add("S-10", **common("S-10", "SYN0000000100", valeur_fonciere="50000",
                     nature_culture="terres", surface_terrain="1000",
                     longitude="5.980000", latitude="45.580000"))

# S-11 — arrondi du prix + nature VEFA.
add("S-11", **common("S-11", "SYN0000000110", valeur_fonciere="118750.49",
                     nature_mutation="Vente en l'état futur d'achèvement",
                     type_local="Appartement", surface_reelle_bati="55",
                     nombre_pieces_principales="2",
                     longitude="5.990000", latitude="45.590000"))

# Ligne invalide : id_mutation vide (40 champs) — ignorée des deux côtés.
add("INVALIDE", **common("", "SYN0000000999",
                         type_local="Maison", surface_reelle_bati="70",
                         longitude="5.880000", latitude="45.480000"))


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        for _, r in rows:
            w.writerow(r)


def interleaved(rows):
    """Entrelace S-05 / S-06 / S-09 (ordre interne préservé), le reste inchangé."""
    mixed_ids = {"S-05", "S-06", "S-09"}
    head = [r for r in rows if r[0] not in mixed_ids]
    queues = {gid: [r for r in rows if r[0] == gid] for gid in sorted(mixed_ids)}
    out, remaining = [], True
    while remaining:
        remaining = False
        for gid in sorted(mixed_ids):
            if queues[gid]:
                out.append(queues[gid].pop(0))
                remaining = bool(any(queues.values())) or remaining
    return head + out


here = os.path.dirname(os.path.abspath(__file__))
write(os.path.join(here, "synthetic.csv"), ROWS)
write(os.path.join(here, "synthetic-desordonne.csv"), interleaved(ROWS))
print(f"synthetic.csv : {len(ROWS)} lignes ; désordonné : S-05/S-06/S-09 entrelacées")
