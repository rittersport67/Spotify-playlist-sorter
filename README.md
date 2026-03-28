# Spotify Playlist Sorter

Pipeline automatique qui classe tes **titres likés Spotify** dans des playlists par genre musical.

Tourne toutes les heures sur GitHub Actions — zéro intervention manuelle.

---

## Comment ça marche

```
Nouveaux likes Spotify
        ↓
   Last.fm tags        →  tags du titre (track.getTopTags)
                       +  tags de l'artiste (artist.getTopTags)
        ↓
   Règles Last.fm      →  matching exact keywords ↔ tags
                          (tags titre prioritaires sur tags artiste)
        ↓ (si ambigu ou aucun match)
   LLM Groq            →  classification par IA (llama-3.1-8b-instant)
                           contexte : titre + artiste + tags + genres du config
        ↓
   Playlists Spotify   →  créées automatiquement par genre
        ↓
   state.json          →  checkpoint committé dans le repo
```

Chaque run ne traite que les **nouveaux likes** depuis le dernier run (incrémental).

---

## Genres configurés

| Genre | Exemples de keywords |
|-------|---------------------|
| Rap FR | french hip hop, rap français, trap français |
| Rap US | hip hop, rap, trap, drill, boom bap |
| EDM | electronic, edm, house, trance, electro |
| Rock | rock, metal, punk, grunge, alternative rock |
| Pop | pop, synth-pop, indie pop, electropop |
| R&B | r&b, soul, neo soul, funk |
| Acoustique | acoustic, folk, singer-songwriter, country |
| Jazz | jazz, bebop, blues, bossa nova |
| K-Pop | k-pop, korean pop, kpop |
| Dubstep | dubstep, brostep, bass music, melodic dubstep |
| Riddim | riddim, riddim dubstep, heavy bass |
| Drum and Bass | dnb, jungle, neurofunk, drumstep |
| Trap | trap music, trap edm, festival trap, melodic trap |
| Hardstyle | hardstyle, hardcore, rawstyle, frenchcore |
| Classique | classical, orchestra, symphony, piano |

Les genres et leurs keywords sont entièrement configurables dans `config.yaml` — sans toucher au code.

---

## Installation

### 1. Prérequis

- Compte [Spotify Developer](https://developer.spotify.com/dashboard) → créer une app
  - Redirect URI : `http://127.0.0.1:8888/callback`
- Compte [Groq](https://console.groq.com) (free tier)
- Compte [Last.fm API](https://www.last.fm/api/account/create) (free)

### 2. Variables d'environnement

Crée un fichier `.env` à la racine :

```env
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
GROQ_API_KEY=...
LASTFM_API_KEY=...
MAX_TRACKS=10        # optionnel, limite le nombre de titres par run
```

### 3. Installer les dépendances

```bash
pip3 install -r requirements.txt
```

### 4. Auth Spotify (une seule fois)

```bash
python3 auth_setup.py
```

Un navigateur s'ouvre → connecte-toi → autorise l'app.
Le terminal affiche un JSON → **copie-le**, il servira pour GitHub Actions.

---

## Déploiement GitHub Actions

### Secrets à configurer

Dans **Settings → Secrets and variables → Actions** :

| Secret | Valeur |
|--------|--------|
| `SPOTIFY_CLIENT_ID` | Client ID Spotify |
| `SPOTIFY_CLIENT_SECRET` | Client Secret Spotify |
| `SPOTIFY_REDIRECT_URI` | `http://127.0.0.1:8888/callback` |
| `SPOTIFY_CACHE` | JSON copié depuis `auth_setup.py` |
| `GROQ_API_KEY` | Clé API Groq |
| `LASTFM_API_KEY` | Clé API Last.fm |

### Variable optionnelle

Dans **Settings → Secrets and variables → Actions → Variables** :

| Variable | Valeur |
|----------|--------|
| `MAX_TRACKS` | Nombre max de titres par run (ex: `100`) |

### Lancer manuellement

**Actions → Spotify Sorter — Run horaire → Run workflow**

---

## Utilisation locale

```bash
# Run complet
python3 sorter.py

# Run limité à 10 titres (pour tester)
MAX_TRACKS=10 python3 sorter.py

# Tester les APIs sur un titre sans rien écrire (state / playlists / logs intacts)
python3 debug.py "Get Low" "DJ Snake"
python3 debug.py                        # utilise le dernier like Spotify
```

---

## Fichiers générés

| Fichier | Description |
|---------|-------------|
| `state.json` | Checkpoint du dernier run (ne pas modifier) |
| `HISTORY.md` | Historique de tous les runs |
| `logs/YYYY-MM-DD_HH-MM-UTC.md` | Détail d'un run (titres classifiés, stats) |

---

## Rollback

```bash
# Voir l'historique de state.json
git log --oneline -- state.json

# Revenir à un état précédent
git checkout <commit_hash> -- state.json
git commit -m "fix: rollback state.json"
git push
```
