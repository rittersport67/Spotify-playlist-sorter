# CLAUDE.md — spotify-sorter

Bienvenue dans **spotify-sorter**. Ce fichier est le point d'entrée pour Claude Code.

## Qu'est-ce que ce projet ?

Pipeline Python automatique qui classe les titres likés Spotify dans des playlists par genre musical, via une classification hybride **Last.fm + LLM Groq**. Tourne toutes les heures sur GitHub Actions.

## Architecture du pipeline

```
Likes Spotify
    ↓
fetch_new_liked_tracks()   → API Spotify /me/tracks (depuis le dernier run)
    ↓
classify_track()
    ├─ fetch_lastfm_tags()  → API Last.fm track.getTopTags
    └─ llm_classify()       → Groq llama-3.1-8b-instant
                              (prompt : titre + artiste + tags Last.fm + genres config)
    ↓
get_or_create_playlist()   → API Spotify /me/playlists + /playlists/{id}/items
    ↓
state.json (checkpoint)    → committé automatiquement par GitHub Actions
```

## Skills disponibles

Lis ces fichiers avant d'intervenir sur le projet :

| Skill | Quand l'utiliser |
|-------|-----------------|
| `.claude/skills/architecture.md` | Avant toute modification structurelle, ajout de fonctionnalité majeure, refactoring |
| `.claude/skills/code-quality.md` | Avant de modifier `sorter.py`, pour une revue de code, pour ajouter une fonction |
| `.claude/skills/deployment.md` | Pour tout ce qui touche au CI/CD, GitHub Actions, secrets, auth Spotify |

## Stack

- **Python 3.12** — script unique `sorter.py`
- **Spotipy** — wrapper Spotify API
- **Last.fm API** — tags musicaux communautaires (classification primaire)
- **Groq** (`llama-3.1-8b-instant`) — classification LLM (fallback si Last.fm insuffisant)
- **GitHub Actions** — cron toutes les heures + commit automatique
- **state.json** — checkpoint incrémental (pas de DB)

## Endpoints Spotify utilisés

| Endpoint | Usage |
|----------|-------|
| `GET /me/tracks` | Récupérer les likes |
| `GET /me/playlists` | Synchroniser les playlists existantes |
| `POST /me/playlists` | Créer une nouvelle playlist |
| `POST /playlists/{id}/items` | Ajouter des titres à une playlist |

> Les endpoints `/audio-features` et `/artists` (batch) sont volontairement absents — ils retournent 403 pour les nouvelles apps Spotify depuis nov. 2024.

## Fichiers critiques

- `sorter.py` — pipeline principal, ne pas casser le flux incrémental
- `config.yaml` — genres et keywords, modifiable sans toucher au code
- `state.json` — **ne jamais modifier manuellement** sauf rollback intentionnel
- `.github/workflows/weekly_sort.yml` — cron et secrets
- `auth_setup.py` — à exécuter une seule fois en local pour générer le token

## Variables d'environnement

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `SPOTIFY_CLIENT_ID` | Oui | ID de l'app Spotify Developer |
| `SPOTIFY_CLIENT_SECRET` | Oui | Secret de l'app Spotify Developer |
| `SPOTIFY_REDIRECT_URI` | Oui | `http://127.0.0.1:8888/callback` |
| `SPOTIFY_CACHE` | Oui (GitHub) | JSON du token généré par `auth_setup.py` |
| `GROQ_API_KEY` | Oui | Clé API Groq |
| `LASTFM_API_KEY` | Recommandé | Clé API Last.fm (améliore la classification) |
| `MAX_TRACKS` | Non | Limite le nombre de titres traités par run |

## Commandes utiles

```bash
# Auth initiale Spotify (une seule fois)
python3 auth_setup.py

# Lancer le sorter en local
python3 sorter.py

# Lancer avec limite de titres
MAX_TRACKS=10 python3 sorter.py

# Vérifier la syntaxe
python3 -m py_compile sorter.py

# Linting
ruff check sorter.py
```

## Règles importantes

1. Toujours lire le skill pertinent avant de modifier du code
2. Les clés API uniquement via `os.environ` — jamais dans le code
3. Toute valeur configurable dans `config.yaml`, pas hardcodée dans `sorter.py`
4. Ne pas appeler les endpoints Spotify `/audio-features` ni `/artists` batch — ils retournent 403
5. Utiliser `sp._post()` / `sp._get()` pour les endpoints non couverts par Spotipy
6. Le LLM Groq est le **fallback final** — Last.fm passe en premier
