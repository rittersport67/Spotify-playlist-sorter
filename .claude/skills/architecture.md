# Skill — Architecture

## Contexte du projet

**spotify-sorter** est un pipeline Python hebdomadaire qui :
1. Lit les nouveaux likes Spotify via l'API officielle (Spotipy)
2. Classe chaque titre par genre (règles déterministes → fallback LLM Groq)
3. Ajoute les titres dans des playlists Spotify
4. Versionne l'état et les logs dans le repo Git via GitHub Actions

---

## Structure du repo

```
spotify-sorter/
├── sorter.py              # Pipeline principal — point d'entrée unique
├── auth_setup.py          # Script one-shot d'auth OAuth Spotify (local uniquement)
├── config.yaml            # Genres, règles audio features, seuils de confiance
├── requirements.txt       # Dépendances Python (spotipy, groq, pyyaml)
├── state.json             # Checkpoint du dernier run (committé automatiquement)
├── HISTORY.md             # Historique global de tous les runs (le + récent en premier)
├── logs/
│   └── YYYY-MM-DD.md      # Rapport détaillé par run
├── .github/
│   └── workflows/
│       └── weekly_sort.yml  # Cron lundi 8h UTC + déclenchement manuel
├── .claude/
│   └── skills/            # Skills Claude pour ce projet
└── .gitignore             # Exclut .spotify_cache, .env, __pycache__
```

---

## Flux de données

```
Spotify API (liked tracks)
        ↓
  fetch_new_liked_tracks()     ← filtre via state.json (last_processed_id)
        ↓
  fetch_audio_features()       ← batch 100 tracks/appel
  fetch_artist_genres()        ← batch 50 artists/appel
        ↓
  rule_based_classify()        ← config.yaml : keywords + audio features
        ↓ (si confidence < threshold)
  llm_classify()               ← Groq llama-3.1-8b-instant
        ↓
  get_or_create_playlist()     ← crée si genre inconnu, stocke ID dans state.json
  add_tracks_to_playlist()     ← batch 100 tracks/appel
        ↓
  state.json + HISTORY.md + logs/   ← commit GitHub Actions
```

---

## Décisions d'architecture clés

### Pas de base de données
L'état est stocké dans `state.json` versionné dans le repo. Zéro infrastructure externe.  
**Limite :** `classified_track_ids` grossit indéfiniment → à purger périodiquement si besoin (au-delà de ~10k titres).

### Classification hybride
- **Règles d'abord** : rapide, gratuit, déterministe. Couvre ~80% des cas.
- **LLM en fallback** : Groq llama-3.1-8b-instant, appelé uniquement si `confidence < threshold`.
- **Un titre = un genre** : simplifie la gestion des playlists. Multi-classification envisageable en v2.

### Mode incrémental
Le script ne traite que les likes postérieurs au `last_processed_id`. Premier run = traitement complet de l'historique.

### Pas de serveur web
Aucun serveur permanent. GitHub Actions gère le scheduling et le commit des fichiers de sortie. Auth Spotify via cache de refresh token injecté comme secret.

---

## Évolutions architecturales possibles

| Évolution | Impact | Complexité |
|-----------|--------|------------|
| Multi-classification (un titre → N playlists) | Modifier `playlist_buckets` en multimap | Faible |
| Rapport par email/webhook | Ajouter step GitHub Actions post-run | Faible |
| Interface de config web | Nouveau composant (frontend léger) | Moyenne |
| Purge automatique de `classified_track_ids` | Logique de fenêtre glissante dans state | Faible |
| Support multi-utilisateurs | Refonte auth + state par user | Élevée |

---

## Contraintes à respecter

- **Rate limits Spotify** : max 100 tracks/appel pour audio_features, 50 artists/appel. Déjà géré en batch.
- **Rate limits Groq** : pause de 0.2s entre chaque appel LLM. Ajuster si volume > 500 titres/run.
- **Refresh token Spotify** : expire si non utilisé > 1 an. Re-run de `auth_setup.py` nécessaire.
- **Taille du commit** : `classified_track_ids` dans state.json peut grossir. Surveiller.

---

## Quand utiliser ce skill

- Avant d'ajouter une nouvelle fonctionnalité majeure : valider l'intégration dans le flux existant
- Pour évaluer une refonte ou un découpage en modules
- Pour discuter des trade-offs entre simplicité et scalabilité
- Pour planifier une évolution de la Phase 3 (voir PRD)
