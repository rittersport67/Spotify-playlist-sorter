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

| Endpoint | Méthode Spotipy | Usage |
|----------|-----------------|-------|
| `GET /me/tracks` | `sp.current_user_saved_tracks(limit, offset)` | Récupérer les likes (paginated, du plus récent au plus ancien) |
| `GET /me/playlists` | `sp._get("me/playlists", limit, offset)` | Synchroniser les playlists existantes |
| `POST /me/playlists` | `sp._post("me/playlists", payload)` | Créer une nouvelle playlist (privée) |
| `POST /playlists/{id}/items` | `sp._post("playlists/{id}/items", payload)` | Ajouter des titres par batch de 100 URIs |

> Les endpoints `/audio-features` et `/artists` (batch) sont volontairement absents — ils retournent 403 pour les nouvelles apps Spotify depuis nov. 2024.

### Scopes OAuth Spotify requis

```
user-library-read
playlist-read-private
playlist-modify-private
playlist-modify-public
```

## Endpoint Last.fm utilisé

| Endpoint | Usage |
|----------|-------|
| `GET https://ws.audioscrobbler.com/2.0/?method=track.getTopTags` | Récupérer les top 15 tags communautaires d'un titre (artist + track) |

Appelé dans `fetch_lastfm_tags()` — retourne `[]` si `LASTFM_API_KEY` absent ou si erreur réseau.

## Fichiers critiques

- `sorter.py` — pipeline principal, ne pas casser le flux incrémental
- `config.yaml` — genres et keywords, modifiable sans toucher au code
- `state.json` — **ne jamais modifier manuellement** sauf rollback intentionnel
- `.github/workflows/weekly_sort.yml` — cron et secrets
- `auth_setup.py` — à exécuter une seule fois en local pour générer le token

## Variables d'environnement

| Variable | Type GitHub | Obligatoire | Description |
|----------|-------------|-------------|-------------|
| `SPOTIFY_CLIENT_ID` | Secret | Oui | ID de l'app Spotify Developer |
| `SPOTIFY_CLIENT_SECRET` | Secret | Oui | Secret de l'app Spotify Developer |
| `SPOTIFY_REDIRECT_URI` | Secret | Oui | `http://127.0.0.1:8888/callback` |
| `SPOTIFY_CACHE` | Secret | Oui (GitHub) | JSON du token généré par `auth_setup.py`, écrit en `.spotify_cache` au run |
| `GROQ_API_KEY` | Secret | Oui | Clé API Groq |
| `LASTFM_API_KEY` | Secret | Recommandé | Clé API Last.fm (améliore la classification) |
| `NTFY_TOPIC` | Secret | Recommandé | Topic ntfy.sh pour les notifications push post-run |
| `MAX_TRACKS` | Variable | Non | Limite le nombre de titres traités par run (défaut : 100) |

## Configuration GitHub Actions (cron)

**Fichier :** `.github/workflows/weekly_sort.yml`

### Déclencheurs

| Déclencheur | Configuration | Description |
|-------------|---------------|-------------|
| `schedule` | `0 * * * *` | Toutes les heures (minute 0) |
| `workflow_dispatch` | — | Lancement manuel depuis l'onglet Actions |

### Steps du job `sort` (runner : `ubuntu-latest`)

| # | Step | Détail |
|---|------|--------|
| 1 | Checkout | `actions/checkout@v4` avec `GITHUB_TOKEN` (permission `contents: write`) |
| 2 | Setup Python | `actions/setup-python@v5` — version `3.12` |
| 3 | Install deps | `pip install -r requirements.txt` |
| 4 | Écriture cache Spotify | `echo '${{ secrets.SPOTIFY_CACHE }}' > .spotify_cache` |
| 5 | Lancer `sorter.py` | Injecte les secrets/variables en variables d'env |
| 6 | Commit auto | `git add state.json HISTORY.md logs/` → commit si diff, puis `git push` |
| 7 | Notification ntfy | Push ntfy.sh (topic `NTFY_TOPIC`) — `always()`, résumé + détail des classifications |

### Commit automatique

```
chore: run YYYY-MM-DD HH:MM UTC — mise à jour état et logs
```
Auteur : `spotify-sorter[bot] <spotify-sorter@users.noreply.github.com>`

### Notification ntfy.sh

- **Succès** → priorité `default`, tags `white_check_mark,spotify`, résumé du run + classifications
- **Échec** → priorité `high`, tags `x,spotify`, message fixe renvoyant vers les logs Actions

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
