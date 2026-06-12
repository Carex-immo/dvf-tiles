# Pont de parité carex.immo ↔ dvf-tiles

`consolidate.py` et `tests/` (test_parity.py, goldens/, fixtures/) sont une **copie
versionnée verbatim** de `carex.immo/tools/dvf-tiles/` au commit `4b95f59` (2026-06-11).
Ils portent les règles de consolidation DVF de l'app iOS, verrouillées par les
golden-masters générés par le test Swift `GeoDvfGoldenTests`.

**Ne JAMAIS modifier ces fichiers ici.** Toute évolution de règle part du Swift
(goldens régénérés consciemment côté carex.immo), puis se propage par recopie +
commit dédié mentionnant le commit source.

Fichiers propres à dvf-tiles (modifiables) :

- `extended.py` — lecture CSV enrichie (adr/cp/com/dep, gzip) qui délègue tout le
  métier aux fonctions importées verbatim de `consolidate.py`.
- `test_parity_extended.py` — rejoue les goldens à travers `extended.py` (preuve de
  non-déviation) et teste l'extraction des champs annexes.

Exécution (bloquante à chaque build, cf. `run_pipeline.sh`) :

```bash
python3 -m pytest -q pipeline/parity
```
