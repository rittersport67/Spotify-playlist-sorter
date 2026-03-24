# Skill — Code Quality & Review

## Objectif

Ce skill guide la revue de code et l'amélioration de la qualité sur le projet **spotify-sorter**.  
Il définit les standards attendus, les points de vigilance spécifiques au projet, et la checklist de review.

---

## Standards du projet

### Style Python
- **Version** : Python 3.12+
- **Type hints** obligatoires sur toutes les fonctions publiques
- **Formatage** : `black` (line-length 100), `isort` pour les imports
- **Linting** : `ruff` (remplace flake8 + pylint)
- Pas de `print()` — utiliser `logging` avec le logger nommé `log`
- Pas de magic numbers inline — les seuils vont dans `config.yaml`

### Nommage
- Fonctions : `snake_case`, verbe d'action (`fetch_`, `classify_`, `get_`, `save_`)
- Variables : descriptives, pas d'abréviations sauf `sp` (Spotipy), `af` (audio features)
- Constantes : `UPPER_SNAKE_CASE` en tête de fichier

### Gestion des erreurs
- Toujours wrapper les appels API (Spotify, Groq) dans un `try/except` avec log explicite
- Ne jamais laisser une exception silencieuse (`except: pass`)
- Les erreurs Spotify 429 (rate limit) doivent déclencher un `time.sleep()` + retry
- Les erreurs Groq doivent fallback sur la règle la plus proche, pas crasher le run

---

## Points de vigilance spécifiques

### API Spotify
```python
# ❌ Mauvais — pas de gestion rate limit
features = sp.audio_features(track_ids)

# ✅ Bon — batch respecté + try/except
for i in range(0, len(track_ids), 100):
    try:
        features = sp.audio_features(track_ids[i:i+100])
    except spotipy.SpotifyException as e:
        log.error(f"Spotify API error: {e}")
        raise
```

### Appels LLM Groq
```python
# ❌ Mauvais — température trop haute, réponse non nettoyée
response = groq_client.chat.completions.create(model=..., temperature=0.9)
return response.choices[0].message.content

# ✅ Bon — température basse, strip systématique, max_tokens limité
response = groq_client.chat.completions.create(
    model=GROQ_MODEL,
    messages=[...],
    max_tokens=20,
    temperature=0.1,
)
return response.choices[0].message.content.strip().strip('"').strip("'")
```

### State JSON
```python
# ❌ Mauvais — écrase sans vérification
with open(STATE_PATH, "w") as f:
    json.dump(state, f)

# ✅ Bon — écriture atomique via fichier temporaire
import tempfile, shutil
with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
    json.dump(state, tmp, indent=2)
shutil.move(tmp.name, STATE_PATH)
```

---

## Checklist de review

### Avant de soumettre du code

**Fonctionnel**
- [ ] La fonction fait une seule chose (SRP)
- [ ] Les cas limites sont gérés (liste vide, None, API down)
- [ ] Pas de régression sur le mode incrémental (last_processed_id respecté)
- [ ] Les batch sizes Spotify sont respectés (100 pour tracks, 50 pour artists)

**Qualité**
- [ ] Type hints présents sur signature de fonction
- [ ] Docstring ou commentaire si la logique n'est pas évidente
- [ ] Pas de code mort ou de TODO non résolu
- [ ] Les logs sont utiles et au bon niveau (DEBUG pour le détail, INFO pour le flux principal)

**Sécurité**
- [ ] Aucune clé API ou token dans le code (tout via `os.environ`)
- [ ] `.spotify_cache` dans `.gitignore`
- [ ] Pas de données utilisateur loggées (noms de playlists privées, etc.)

**Config**
- [ ] Toute valeur configurable est dans `config.yaml`, pas hardcodée
- [ ] Un nouveau genre dans config.yaml a bien `keywords`, `audio_features`, et `confidence_threshold`

---

## Commandes de vérification locale

```bash
# Install dev deps
pip install ruff black isort

# Linting
ruff check sorter.py auth_setup.py

# Formatage (dry-run)
black --check --line-length 100 sorter.py
isort --check-only sorter.py

# Formatage (apply)
black --line-length 100 sorter.py
isort sorter.py

# Vérification syntaxe
python -m py_compile sorter.py && echo "OK"
```

---

## Anti-patterns à éviter

| Anti-pattern | Pourquoi | Alternative |
|-------------|----------|-------------|
| `except Exception: pass` | Masque les erreurs | Logger + raise ou fallback explicite |
| Appels Spotify sans batch | Rate limit 429 | Toujours batcher à 100/50 |
| LLM à temperature > 0.3 | Réponses instables pour classification | Garder 0.1 |
| `print()` au lieu de `logging` | Invisible dans GitHub Actions logs | `log.info()` |
| Modifier `state.json` sans le sauvegarder | Perte de checkpoint en cas de crash | `save_state()` après chaque modification critique |
| Hardcoder un genre dans le code | Rigide, non configurable | Tout dans `config.yaml` |

---

## Quand utiliser ce skill

- Avant de merger du nouveau code sur `main`
- Quand on ajoute une nouvelle fonction de classification ou d'appel API
- Quand on modifie la logique de gestion du state
- Pour refactorer `sorter.py` si le fichier dépasse ~400 lignes (envisager un découpage en modules)
