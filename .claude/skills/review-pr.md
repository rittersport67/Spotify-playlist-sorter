# Skill — Review de Pull Request

## Objectif

Guider une revue complète d'une PR sur **spotify-sorter** en appliquant successivement :
1. La lecture du contenu de la PR (diff, description, fichiers modifiés)
2. La grille d'architecture (`.claude/skills/architecture.md`)
3. La grille de qualité de code (`.claude/skills/code-quality.md`)
4. Un verdict final structuré

---

## Étape 1 — Lire la PR

Utiliser les outils GitHub MCP pour collecter toutes les informations nécessaires **avant** toute analyse.

### Informations à récupérer

```
mcp__github__pull_request_read   → titre, description, branche source/cible, auteur, statut CI
mcp__github__get_file_contents   → fichiers modifiés (sorter.py, config.yaml, workflow, etc.)
mcp__github__list_commits        → liste des commits de la PR
```

### Ce qu'il faut noter

- **Objectif déclaré** : que prétend faire la PR ? (description, titre)
- **Fichiers touchés** : quels composants sont impactés ?
- **Taille du changement** : combien de lignes ajoutées / supprimées ?
- **Tests / CI** : la PR passe-t-elle les checks automatiques ?

---

## Étape 2 — Grille Architecture

Lire `.claude/skills/architecture.md` puis évaluer chaque point ci-dessous.

### Checklist Architecture

**Flux du pipeline**
- [ ] Le flux `fetch → classify → add_to_playlist → save_state` est préservé
- [ ] Le mode incrémental (`last_processed_id`) n'est pas cassé
- [ ] `state.json` est toujours sauvegardé après chaque modification critique

**Endpoints & API**
- [ ] Aucun appel aux endpoints interdits (`/audio-features`, `/artists` batch) — retournent 403
- [ ] Les nouveaux appels Spotify utilisent `sp._get()` / `sp._post()` si non couverts par Spotipy
- [ ] Les nouveaux appels Last.fm passent bien par `fetch_lastfm_tags()`

**Configuration**
- [ ] Toute nouvelle valeur configurable est dans `config.yaml`, pas hardcodée dans `sorter.py`
- [ ] Un nouveau genre dans `config.yaml` possède bien `keywords`, `audio_features`, `confidence_threshold`

**Scalabilité & contraintes**
- [ ] Les batch sizes Spotify sont respectés (100 tracks, 50 artists)
- [ ] Pas de régression sur la gestion de `classified_track_ids` (croissance du state)
- [ ] Les rate limits Groq sont respectés (pause 0.2s entre appels LLM)

---

## Étape 3 — Grille Code Quality

Lire `.claude/skills/code-quality.md` puis évaluer chaque point ci-dessous.

### Checklist Code Quality

**Style & standards**
- [ ] Python 3.12+ : type hints présents sur toutes les fonctions publiques modifiées
- [ ] Nommage cohérent : `snake_case`, verbes d'action (`fetch_`, `classify_`, `get_`, `save_`)
- [ ] Pas de `print()` — uniquement `log.info()` / `log.error()` / `log.warning()`
- [ ] Pas de magic numbers inline — seuils dans `config.yaml`

**Gestion des erreurs**
- [ ] Appels API (Spotify, Groq, Last.fm) wrappés dans `try/except` avec log explicite
- [ ] Pas d'`except: pass` silencieux
- [ ] Les erreurs Spotify 429 déclenchent un `time.sleep()` + retry
- [ ] Les erreurs Groq ne crashent pas le run (fallback explicite)

**Sécurité**
- [ ] Aucune clé API ou token dans le code (tout via `os.environ`)
- [ ] `.spotify_cache` non committé (présent dans `.gitignore`)
- [ ] Pas de données utilisateur sensibles loggées

**Qualité générale**
- [ ] Chaque fonction fait une seule chose (SRP)
- [ ] Les cas limites sont gérés (liste vide, `None`, API down)
- [ ] Pas de code mort, pas de TODO non résolu
- [ ] Logs au bon niveau (DEBUG pour le détail, INFO pour le flux principal)

---

## Étape 4 — Verdict final

Après avoir complété les deux grilles, produire un rapport structuré.

### Format du rapport

```
## Revue PR #<numéro> — <titre>

### Résumé
<1-2 phrases décrivant ce que fait la PR>

### Architecture — <PASS / WARN / FAIL>
<liste des points validés ✅ et des problèmes ❌ avec explication>

### Code Quality — <PASS / WARN / FAIL>
<liste des points validés ✅ et des problèmes ❌ avec explication>

### Points bloquants
<liste des problèmes qui empêchent le merge — vide si aucun>

### Suggestions (non bloquantes)
<améliorations optionnelles>

### Verdict final
- ✅ APPROUVÉE — peut être mergée
- ⚠️  APPROUVÉE AVEC RÉSERVES — merger après correction des points WARN
- ❌ CHANGEMENTS DEMANDÉS — corrections bloquantes requises
```

### Règles de décision

| Condition | Verdict |
|-----------|---------|
| Aucun FAIL, aucun WARN | ✅ APPROUVÉE |
| Aucun FAIL, ≥1 WARN mineur | ⚠️ APPROUVÉE AVEC RÉSERVES |
| ≥1 FAIL sur architecture ou sécurité | ❌ CHANGEMENTS DEMANDÉS |
| CI en échec | ❌ CHANGEMENTS DEMANDÉS (bloquer jusqu'à correction) |

---

## Quand utiliser ce skill

- Avant de merger toute PR vers `main`
- Quand on est assigné reviewer sur une PR
- Pour auto-review d'une branche feature avant de demander une review humaine
- En réponse à `"review la PR #X"` ou `"valide cette PR"`
