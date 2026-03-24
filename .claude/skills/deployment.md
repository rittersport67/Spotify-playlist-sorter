# Skill — Déploiement

## Vue d'ensemble

**spotify-sorter** tourne entièrement sur **GitHub Actions** — aucun serveur à gérer.  
Le déploiement se résume à : configurer les secrets → pousser le code → lancer le premier run.

---

## Prérequis

- Compte GitHub avec un repo `spotify-sorter` (public ou privé)
- Compte Spotify Developer : [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
- Compte Groq (free tier) : [console.groq.com](https://console.groq.com)
- Python 3.12+ installé en local (pour l'auth initiale uniquement)

---

## Étape 1 — App Spotify Developer

1. Aller sur [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Cliquer **Create App**
3. Remplir :
   - App name : `spotify-sorter` (ou autre)
   - Redirect URI : `http://localhost:8888/callback`
4. Noter le **Client ID** et **Client Secret** (onglet Settings)

---

## Étape 2 — Auth initiale (une seule fois en local)

Cette étape génère le refresh token Spotify qui sera injecté dans GitHub Actions.

```bash
# Cloner le repo en local
git clone https://github.com/<toi>/spotify-sorter.git
cd spotify-sorter

# Installer les dépendances
pip3 install -r requirements.txt

# Lancer l'auth
SPOTIFY_CLIENT_ID=<client_id> \
SPOTIFY_CLIENT_SECRET=<client_secret> \
SPOTIFY_REDIRECT_URI=http://localhost:8888/callback \
python auth_setup.py
```

Un navigateur s'ouvre → **Agree** → tu es redirigé vers `localhost:8888/callback`.  
Le script affiche le contenu JSON de `.spotify_cache` dans le terminal → **copier ce JSON**.

> ⚠️ Ne jamais committer `.spotify_cache` (déjà dans `.gitignore`)

---

## Étape 3 — Secrets GitHub Actions

Dans le repo GitHub : **Settings → Secrets and variables → Actions → New repository secret**
 
| Nom du secret | Valeur |
|---------------|--------|
| `SPOTIFY_CLIENT_ID` | Client ID de l'app Spotify |
| `SPOTIFY_CLIENT_SECRET` | Client Secret de l'app Spotify |
| `SPOTIFY_REDIRECT_URI` | `http://localhost:8888/callback` |
| `SPOTIFY_CACHE` | Le JSON complet copié depuis `auth_setup.py` |
| `GROQ_API_KEY` | Clé API depuis [console.groq.com/keys](https://console.groq.com/keys) |

---

## Étape 4 — Premier run

1. Pousser le code sur `main` si ce n'est pas déjà fait :
   ```bash
   git add .
   git commit -m "feat: initial setup"
   git push origin main
   ```

2. Aller dans **Actions → Spotify Sorter — Run hebdomadaire → Run workflow**

3. Surveiller les logs en temps réel dans l'interface GitHub Actions

4. Vérifier :
   - `state.json` créé et committé automatiquement
   - `HISTORY.md` et `logs/YYYY-MM-DD.md` apparus dans le repo
   - Playlists créées dans Spotify

---

## Scheduling

Le workflow tourne automatiquement **chaque lundi à 8h00 UTC** (9h ou 10h heure française selon DST).

Pour modifier le créneau, éditer `.github/workflows/weekly_sort.yml` :
```yaml
- cron: "0 8 * * 1"   # minute heure jour_mois mois jour_semaine
#         ↑ 8h UTC, lundi (1)
```

Exemples :
- Dimanche soir 22h UTC : `"0 22 * * 0"`
- Vendredi midi UTC : `"0 12 * * 5"`

---

## Renouvellement du refresh token

Le refresh token Spotify expire si l'app n'est pas utilisée pendant **plus d'un an**, ou si tu révokes l'accès.

En cas d'erreur `401 Unauthorized` dans les logs Actions :

1. Relancer `auth_setup.py` en local (même commande qu'étape 2)
2. Mettre à jour le secret `SPOTIFY_CACHE` avec le nouveau JSON
3. Relancer le workflow manuellement

---

## Rollback

En cas de bug introduit par un run qui a mal modifié `state.json` :

```bash
# Voir l'historique des commits de state.json
git log --oneline -- state.json

# Revenir à un état précédent
git checkout <commit_hash> -- state.json
git commit -m "fix: rollback state.json to <date>"
git push
```

Pour rejouer un run sur une période spécifique, modifier manuellement `last_processed_id` dans `state.json` avec l'ID Spotify du dernier titre à re-traiter, puis relancer le workflow.

---

## Monitoring

### Logs GitHub Actions
Chaque run produit des logs structurés visibles dans l'onglet Actions.  
Les lignes `[INFO]` résument le flux, `[ERROR]` signalent les problèmes.

### Logs versionnés
- `HISTORY.md` : vue globale de tous les runs dans le repo
- `logs/YYYY-MM-DD.md` : détail d'un run spécifique

### Alertes d'échec
GitHub envoie automatiquement un email si un workflow échoue.  
Activer dans : **Settings → Notifications → Actions**.

---

## Limites & quotas

| Service | Limite | Impact |
|---------|--------|--------|
| Spotify API | ~180 req/min (rolling) | Géré via batch + pause |
| Groq free tier | ~30 req/min, 500k tokens/jour | Suffisant pour <2000 titres/run |
| GitHub Actions | 2000 min/mois (free) | Un run ≈ 2-5 min → largement suffisant |
| GitHub repo | 1 GB storage | `state.json` + logs restent petits |

---

## Quand utiliser ce skill

- Pour le setup initial du projet sur un nouveau compte
- En cas d'erreur d'auth Spotify (token expiré, révoqué)
- Pour modifier le scheduling du cron
- Pour débugger un run GitHub Actions en échec
- Pour effectuer un rollback après un run problématique
