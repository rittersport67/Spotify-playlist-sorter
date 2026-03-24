import os
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from groq import Groq
import yaml

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
STATE_PATH = BASE_DIR / "state.json"
HISTORY_PATH = BASE_DIR / "HISTORY.md"
LOGS_DIR = BASE_DIR / "logs"

GROQ_MODEL = "llama-3.1-8b-instant"
SPOTIFY_SCOPE = (
    "user-library-read "
    "playlist-read-private "
    "playlist-modify-private "
    "playlist-modify-public"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — state
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"last_processed_id": None, "playlist_ids": {}}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Helpers — config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Spotify
# ---------------------------------------------------------------------------

def get_spotify_client() -> spotipy.Spotify:
    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=os.environ["SPOTIFY_CLIENT_ID"],
            client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
            redirect_uri=os.environ["SPOTIFY_REDIRECT_URI"],
            scope=SPOTIFY_SCOPE,
            cache_path=BASE_DIR / ".spotify_cache",
            open_browser=False,
        )
    )


def fetch_new_liked_tracks(sp: spotipy.Spotify, last_id: Optional[str]) -> list[dict]:
    """
    Retourne les titres likés plus récents que last_id.
    L'API Spotify renvoie les likes du plus récent au plus ancien.
    """
    tracks = []
    offset = 0
    limit = 50

    while True:
        batch = sp.current_user_saved_tracks(limit=limit, offset=offset)
        items = batch["items"]

        if not items:
            break

        for item in items:
            track = item["track"]
            if track is None:
                continue
            if last_id and track["id"] == last_id:
                return tracks  # on a rattrapé le dernier run
            tracks.append({
                "id": track["id"],
                "name": track["name"],
                "artist": track["artists"][0]["name"],
                "artist_id": track["artists"][0]["id"],
                "added_at": item["added_at"],
            })

        if batch["next"] is None:
            break
        offset += limit

    return tracks


def fetch_audio_features(sp: spotipy.Spotify, track_ids: list[str]) -> dict[str, dict]:
    """Retourne un dict {track_id: features}. Batch de 100 max.
    Retourne un dict vide si l'endpoint est inaccessible (403)."""
    result = {}
    for i in range(0, len(track_ids), 100):
        batch_ids = track_ids[i:i + 100]
        try:
            features = sp.audio_features(batch_ids) or []
            for f in features:
                if f:
                    result[f["id"]] = f
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 403:
                log.warning("Audio features inaccessibles (403) — classification sans features audio.")
                return {}
            raise
    return result


def fetch_artist_genres(sp: spotipy.Spotify, artist_ids: list[str]) -> dict[str, list[str]]:
    """Retourne un dict {artist_id: [genres]}. Batch de 50 max."""
    result = {}
    unique_ids = list(set(artist_ids))
    for i in range(0, len(unique_ids), 50):
        batch = sp.artists(unique_ids[i:i + 50])
        for artist in batch["artists"]:
            if artist:
                result[artist["id"]] = artist.get("genres", [])
    return result


def get_or_create_playlist(sp: spotipy.Spotify, name: str, state: dict) -> str:
    """Retourne l'ID d'une playlist, la crée si elle n'existe pas."""
    playlist_ids: dict = state.setdefault("playlist_ids", {})

    if name in playlist_ids:
        return playlist_ids[name]

    user_id = sp.current_user()["id"]
    playlist = sp.user_playlist_create(
        user=user_id,
        name=name,
        public=False,
        description=f"Auto-générée par Spotify Sorter — {name}",
    )
    playlist_ids[name] = playlist["id"]
    log.info(f"Playlist créée : '{name}' ({playlist['id']})")
    return playlist["id"]


def add_tracks_to_playlist(sp: spotipy.Spotify, playlist_id: str, track_ids: list[str]) -> None:
    """Ajoute des titres par batch de 100."""
    for i in range(0, len(track_ids), 100):
        sp.playlist_add_items(playlist_id, track_ids[i:i + 100])


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def rule_based_classify(
    track: dict,
    features: dict,
    artist_genres: list[str],
    genre_rules: dict,
) -> Optional[tuple[str, float]]:
    """
    Tente de classifier le titre par règles.
    Retourne (genre_name, confidence) ou None si ambigu.
    """
    artist_genres_lower = [g.lower() for g in artist_genres]

    for genre_name, rules in genre_rules.items():
        score = 0.0
        hits = 0

        # Correspondance sur les genres Spotify de l'artiste
        keywords = [k.lower() for k in rules.get("keywords", [])]
        for keyword in keywords:
            for ag in artist_genres_lower:
                if keyword in ag:
                    score += 0.6
                    hits += 1
                    break

        # Règles sur les audio features
        af_rules = rules.get("audio_features", {})
        for feature, condition in af_rules.items():
            if feature not in features:
                continue
            value = features[feature]
            passed = False
            if "min" in condition and value >= condition["min"]:
                passed = True
            if "max" in condition and value <= condition["max"]:
                passed = True
            if "min" in condition and "max" in condition:
                passed = value >= condition["min"] and value <= condition["max"]
            if passed:
                score += 0.3
                hits += 1

        if hits > 0:
            confidence = min(score, 1.0)
            if confidence >= rules.get("confidence_threshold", 0.6):
                return (genre_name, confidence)

    return None


def llm_classify(
    groq_client: Groq,
    track: dict,
    features: dict,
    artist_genres: list[str],
    available_genres: list[str],
) -> str:
    """
    Classifie via Groq llama-3.1-8b-instant.
    Peut retourner un genre de la liste ou en créer un nouveau.
    """
    genres_str = ", ".join(available_genres)
    af = {
        k: round(features.get(k, 0), 2)
        for k in ["energy", "danceability", "acousticness", "valence", "speechiness", "tempo"]
    }

    prompt = f"""Tu es un expert en classification musicale. Classe ce titre dans UN genre parmi la liste, ou propose un nouveau genre court si aucun ne convient.

Titre : {track['name']}
Artiste : {track['artist']}
Genres Spotify de l'artiste : {', '.join(artist_genres) or 'inconnu'}
Audio features : {json.dumps(af)}

Genres disponibles : {genres_str}

Réponds UNIQUEMENT avec le nom du genre (un seul mot ou expression courte, ex: "Hip-Hop", "Électro", "K-Pop"). Aucune explication."""

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=20,
        temperature=0.1,
    )
    return response.choices[0].message.content.strip().strip('"').strip("'")


def classify_track(
    track: dict,
    features: Optional[dict],
    artist_genres: list[str],
    genre_rules: dict,
    groq_client: Groq,
    available_genres: list[str],
    stats: dict,
) -> str:
    """Pipeline de classification : règles d'abord, LLM si ambigu."""
    if features is None:
        features = {}

    result = rule_based_classify(track, features, artist_genres, genre_rules)

    if result:
        genre, confidence = result
        stats["rule_classified"] += 1
        log.debug(f"  [rules] '{track['name']}' → {genre} (conf: {confidence:.2f})")
        return genre

    # Fallback LLM
    stats["llm_classified"] += 1
    genre = llm_classify(groq_client, track, features, artist_genres, available_genres)
    log.debug(f"  [llm]   '{track['name']}' → {genre}")
    return genre


# ---------------------------------------------------------------------------
# Logging / rapport
# ---------------------------------------------------------------------------

def generate_run_report(
    run_date: str,
    stats: dict,
    classifications: list[dict],
) -> str:
    lines = [
        f"# Run du {run_date}",
        "",
        "## Résumé",
        "",
        f"| Métrique | Valeur |",
        f"|----------|--------|",
        f"| Titres traités | {stats['total']} |",
        f"| Ajoutés aux playlists | {stats['added']} |",
        f"| Ignorés (déjà classés) | {stats['skipped']} |",
        f"| Classifiés par règles | {stats['rule_classified']} |",
        f"| Classifiés par LLM | {stats['llm_classified']} |",
        f"| Nouvelles playlists créées | {stats['new_playlists']} |",
        "",
    ]

    if classifications:
        lines += [
            "## Détail des classifications",
            "",
            "| Titre | Artiste | Genre | Méthode |",
            "|-------|---------|-------|---------|",
        ]
        for c in classifications:
            lines.append(
                f"| {c['name']} | {c['artist']} | {c['genre']} | {c['method']} |"
            )
        lines.append("")

    return "\n".join(lines)


def update_history(report: str, run_date: str) -> None:
    """Prepend le rapport dans HISTORY.md et écrit le fichier de log du jour."""
    # Log individuel
    LOGS_DIR.mkdir(exist_ok=True)
    log_file = LOGS_DIR / f"{run_date}.md"
    log_file.write_text(report)

    # HISTORY.md — le plus récent en premier
    separator = "\n---\n\n"
    if HISTORY_PATH.exists():
        existing = HISTORY_PATH.read_text()
        HISTORY_PATH.write_text(report + separator + existing)
    else:
        HISTORY_PATH.write_text(report)

    log.info(f"Logs écrits : logs/{run_date}.md + HISTORY.md")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== Spotify Sorter — démarrage ===")
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    config = load_config()
    state = load_state()
    genre_rules: dict = config.get("genres", {})
    available_genres = list(genre_rules.keys())

    sp = get_spotify_client()
    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

    stats = {
        "total": 0,
        "added": 0,
        "skipped": 0,
        "rule_classified": 0,
        "llm_classified": 0,
        "new_playlists": 0,
    }
    classifications: list[dict] = []
    already_classified: set = set(state.get("classified_track_ids", []))

    # 1. Fetch nouveaux likes
    last_id = state.get("last_processed_id")
    log.info(f"Dernier ID traité : {last_id or 'aucun (premier run)'}")
    tracks = fetch_new_liked_tracks(sp, last_id)
    log.info(f"{len(tracks)} nouveaux titres à traiter")

    if not tracks:
        log.info("Rien de nouveau. Fin du run.")
        update_history(
            generate_run_report(run_date, stats, classifications),
            run_date,
        )
        return

    stats["total"] = len(tracks)

    # 2. Audio features + genres artistes (batch)
    track_ids = [t["id"] for t in tracks]
    artist_ids = [t["artist_id"] for t in tracks]

    log.info("Récupération des audio features…")
    all_features = fetch_audio_features(sp, track_ids)

    log.info("Récupération des genres artistes…")
    all_artist_genres = fetch_artist_genres(sp, artist_ids)

    # 3. Classification + ajout dans playlists
    playlist_buckets: dict[str, list[str]] = {}  # genre → [track_ids]
    new_last_id = tracks[0]["id"]  # le plus récent

    for track in tracks:
        if track["id"] in already_classified:
            stats["skipped"] += 1
            continue

        features = all_features.get(track["id"])
        artist_genres = all_artist_genres.get(track["artist_id"], [])

        genre = classify_track(
            track=track,
            features=features,
            artist_genres=artist_genres,
            genre_rules=genre_rules,
            groq_client=groq_client,
            available_genres=available_genres,
            stats=stats,
        )

        method = "LLM" if stats["llm_classified"] > 0 and stats["rule_classified"] == 0 else "Règles"
        # Recalcul précis de la méthode pour ce titre
        prev_llm = stats["llm_classified"]
        method = "LLM" if prev_llm > 0 else "Règles"

        playlist_buckets.setdefault(genre, []).append(track["id"])
        classifications.append({
            "name": track["name"],
            "artist": track["artist"],
            "genre": genre,
            "method": method,
        })

        # Si genre inconnu, on l'ajoute pour les prochaines classifications
        if genre not in available_genres:
            available_genres.append(genre)
            log.info(f"Nouveau genre détecté : '{genre}'")

        already_classified.add(track["id"])
        stats["added"] += 1

        # Pause légère pour éviter rate limits Groq
        time.sleep(0.2)

    # 4. Ajout dans les playlists Spotify
    prev_playlist_count = len(state.get("playlist_ids", {}))

    for genre, ids in playlist_buckets.items():
        playlist_id = get_or_create_playlist(sp, genre, state)
        add_tracks_to_playlist(sp, playlist_id, ids)
        log.info(f"'{genre}' : {len(ids)} titre(s) ajouté(s)")

    stats["new_playlists"] = len(state.get("playlist_ids", {})) - prev_playlist_count

    # 5. Sauvegarde état
    state["last_processed_id"] = new_last_id
    state["classified_track_ids"] = list(already_classified)
    save_state(state)

    # 6. Rapport
    report = generate_run_report(run_date, stats, classifications)
    update_history(report, run_date)

    log.info("=== Run terminé ===")
    log.info(
        f"Traités: {stats['total']} | "
        f"Ajoutés: {stats['added']} | "
        f"Ignorés: {stats['skipped']} | "
        f"Nouvelles playlists: {stats['new_playlists']}"
    )


if __name__ == "__main__":
    main()
