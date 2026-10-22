#!/usr/bin/env python3
"""CAREX - Extraction d'une periode d'un CSV geo-dvf archive, ids renumerotes.

Cas d'usage : la livraison DVF courante commence au 2nd semestre 2021
(2021s2_full.csv.gz) ; le 1er semestre ne subsiste que dans l'ancien
2021_full.csv.gz. On en extrait les mutations datees avant --avant, en
decalant le numero d'id_mutation de --decalage : les deux livraisons
numerotent chacune a partir de AAAA-1 (collision -> prepare.py echoue sur
les doublons). Le format AAAA-N est conserve.

  python3 pipeline/extract_semestre.py data/raw/archive/2021_full.csv.gz \\
      data/raw/2021s1_full.csv.gz --avant 2021-07-01 --decalage 2000000

Le CSV est relu/reecrit par le module csv (memes regles que consolidate.py) :
seules la colonne id_mutation et la selection des lignes changent. Une mutation
a cheval sur la date de coupure fait echouer l'extraction (elle serait tronquee).
"""
import argparse
import csv
import gzip
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("sortie")
    ap.add_argument("--avant", required=True, help="date de coupure exclue, AAAA-MM-JJ")
    ap.add_argument("--decalage", type=int, required=True,
                    help="ajoute au numero N de l'id AAAA-N")
    args = ap.parse_args()

    gardees, ignorees = set(), set()
    n_lignes = 0
    with gzip.open(args.source, "rt", encoding="utf-8", newline="") as fi, \
         gzip.open(args.sortie, "wt", encoding="utf-8", newline="") as fo:
        reader = csv.reader(fi)
        writer = csv.writer(fo, lineterminator="\n")
        header = next(reader)
        i_id, i_date = header.index("id_mutation"), header.index("date_mutation")
        writer.writerow(header)
        for row in reader:
            mid = row[i_id]
            if row[i_date] >= args.avant:
                ignorees.add(mid)
                continue
            gardees.add(mid)
            annee, num = mid.split("-")
            row[i_id] = f"{annee}-{int(num) + args.decalage}"
            writer.writerow(row)
            n_lignes += 1

    a_cheval = gardees & ignorees
    if a_cheval:
        print(f"ERREUR : {len(a_cheval)} mutations a cheval sur {args.avant} "
              f"(ex: {sorted(a_cheval)[:3]})", file=sys.stderr)
        return 1
    print(f"{args.sortie} : {n_lignes} lignes, {len(gardees)} mutations "
          f"(avant {args.avant}, ids +{args.decalage})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
