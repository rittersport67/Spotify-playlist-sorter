# CLAUDE.md — spotify-sorter

Bienvenue dans **spotify-sorter**. Ce fichier est le point d'entrée pour Claude Code.

## Qu'est-ce que ce projet ?

Pipeline Python hebdomadaire qui classe automatiquement les titres likés Spotify dans des playlists par genre musical, via une classification hybride (règles déterministes + LLM Groq).

## Skills disponibles

Lis ces fichiers avant d'intervenir sur le projet :

| Skill | Quand l'utiliser |
|-------|-----------------|
| `.claude/skills/architecture.md` | Avant toute modification structurelle, ajout de fonctionnalité majeure, refactoring |
| `.claude/skills/code-quality.md` | Avant de modifier `sorter.py`, pour une revue de code, pour ajouter une fonction |
| `.claude/skills/deployment.md` | Pour tout ce qui touche au CI/CD, GitHub Actions, secrets, auth Spotify |

## Stack en un coup d'œil

- **Python 3.12** — script unique `sorter.py`
- **Spotipy** — wrapper Spotify API
- **Groq** (`llama-3.1-8b-instant`) — classification LLM des cas ambigus
- **GitHub Actions** — scheduling cron (lundi 8h UTC) + commit automatique
- **state.json** — checkpoint incrémental (pas de DB)

## Fichiers critiques

- `sorter.py` — pipeline principal, ne pas casser le flux incrémental
- `config.yaml` — genres et règles, modifiable sans toucher au code
- `state.json` — **ne jamais modifier manuellement** sauf rollback intentionnel
- `.github/workflows/weekly_sort.yml` — cron et secrets

## Commandes utiles

```bash
# Vérifier la syntaxe avant de pusher
python3 -m py_compile sorter.py

# Linting
ruff check sorter.py

# Auth initiale Spotify (une seule fois)
SPOTIFY_CLIENT_ID=xxx SPOTIFY_CLIENT_SECRET=yyy SPOTIFY_REDIRECT_URI=http://localhost:8888/callback python3 auth_setup.py
```

## Règles importantes

1. Toujours lire le skill pertinent avant de modifier du code
2. Les clés API uniquement via `os.environ` — jamais dans le code
3. Toute valeur configurable dans `config.yaml`, pas hardcodée dans `sorter.py`
4. Respecter les batch sizes Spotify : 100 pour `audio_features`, 50 pour `artists`
5. Le LLM Groq est un **fallback** — ne pas l'appeler si les règles suffisent
