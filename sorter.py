import os
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from groq import Groq
import yaml
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
STATE_PATH = BASE_DIR / "state.json"
HISTORY_PATH = BASE_DIR / "HISTORY.md"
LOGS_DIR = BASE_DIR / "logs"

GROQ_MODEL = "llama-3.1-8b-instant"
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY")
MAX_TRACKS = int(os.environ["MAX_TRACKS"]) if os.environ.get("MAX_TRACKS") else 100
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
            release_date_raw: str = track.get("album", {}).get("release_date", "") or ""
            release_year: Optional[int] = int(release_date_raw[:4]) if release_date_raw[:4].isdigit() else None
            tracks.append({
                "id": track["id"],
                "name": track["name"],
                "artist": track["artists"][0]["name"],
                "artist_id": track["artists"][0]["id"],
                "all_artists": [a["name"] for a in track.get("artists", [])],
                "added_at": item["added_at"],
                "popularity": track.get("popularity"),
                "duration_ms": track.get("duration_ms"),
                "album_name": track.get("album", {}).get("name"),
                "release_year": release_year,
                "explicit": track.get("explicit", False),
            })

        if batch["next"] is None:
            break
        offset += limit

    return tracks



def fetch_lastfm_artist_tags(artist: str) -> list[str]:
    """Retourne les top tags Last.fm d'un artiste via artist.getTopTags (vide si API non configurée ou erreur)."""
    if not LASTFM_API_KEY:
        return []
    try:
        response = requests.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "artist.getTopTags",
                "artist": artist,
                "api_key": LASTFM_API_KEY,
                "format": "json",
            },
            timeout=5,
        )
        tags = response.json().get("toptags", {}).get("tag", [])
        tags_sorted = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)
        result = [t["name"].lower() for t in tags_sorted[:10]]
        log.info(f"  [lastfm] artiste {artist!r} → tags : {result or 'aucun'}")
        return result
    except Exception as exc:
        log.warning(f"fetch_lastfm_artist_tags: artiste {artist!r} inaccessible — {exc}")
        return []


def fetch_existing_playlists(sp: spotipy.Spotify) -> dict[str, str]:
    """Retourne un dict {nom_playlist: id} des playlists de l'utilisateur."""
    result = {}
    offset = 0
    while True:
        data = sp._get("me/playlists", limit=50, offset=offset)
        for item in data.get("items", []):
            if item:
                result[item["name"]] = item["id"]
        if data.get("next") is None:
            break
        offset += 50
    return result


def get_or_create_playlist(sp: spotipy.Spotify, name: str, state: dict) -> str:
    """Retourne l'ID d'une playlist, la crée si elle n'existe pas."""
    playlist_ids: dict = state.setdefault("playlist_ids", {})

    if name in playlist_ids:
        return playlist_ids[name]

    playlist = sp._post("me/playlists", payload={
        "name": name,
        "public": False,
        "description": f"Auto-générée par Spotify Sorter — {name}",
    })
    playlist_ids[name] = playlist["id"]
    log.info(f"Playlist créée : '{name}' ({playlist['id']})")
    return playlist["id"]


def add_tracks_to_playlist(sp: spotipy.Spotify, playlist_id: str, track_ids: list[str]) -> None:
    """Ajoute des titres par batch de 100."""
    for i in range(0, len(track_ids), 100):
        uris = [f"spotify:track:{tid}" for tid in track_ids[i:i + 100]]
        sp._post(f"playlists/{playlist_id}/items", payload={"uris": uris})


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _norm_tag(s: str) -> str:
    """Normalise un tag/keyword : minuscules, sans tirets ni espaces."""
    return s.lower().replace("-", "").replace(" ", "")


def rule_based_classify(
    artist_tags: list[str],
    track_tags: list[str],
    genre_rules: dict,
) -> Optional[str]:
    """
    Tente de classifier par correspondance exacte tags Last.fm ↔ keywords config.
    Tags du titre (poids 1.0) ont priorité sur tags artiste (poids 0.7).
    Chaque keyword ne compte qu'une fois — si match track ET artiste, on prend le meilleur.
    Retourne le genre gagnant si score unique, None si tie ou aucun match.
    """
    track_norms = {_norm_tag(t) for t in track_tags}
    artist_norms = {_norm_tag(t) for t in artist_tags}
    scored: dict[str, float] = {}

    for genre_name, rules in genre_rules.items():
        score = 0.0
        for keyword in rules.get("keywords", []):
            kw = _norm_tag(keyword)
            if kw in track_norms:
                score += 1.0
            elif kw in artist_norms:
                score += 0.7
        if score > 0:
            scored[genre_name] = score

    if not scored:
        return None

    best_score = max(scored.values())
    winners = [g for g, s in scored.items() if s == best_score]

    # Tie → ambiguïté, laisser le LLM trancher
    if len(winners) > 1:
        return None

    return winners[0]


def build_llm_prompt(
    track: dict,
    available_genres: list[str],
    lastfm_tags: list[str],
    genre_rules: dict,
) -> str:
    """Construit le prompt de classification pour le LLM."""
    tags_str = ", ".join(lastfm_tags) if lastfm_tags else "aucun"
    genres_context = "\n".join(
        f"- {name} (mots-clés : {', '.join(rules.get('keywords', []))})"
        for name, rules in genre_rules.items()
    )
    genres_list = ", ".join(available_genres)

    all_artists = track.get("all_artists", [])
    artists_str = ", ".join(all_artists) if len(all_artists) > 1 else track["artist"]
    artist_genres_str = ", ".join(track.get("artist_genres", [])) or "inconnus"
    popularity_str = str(track["popularity"]) if track.get("popularity") is not None else "inconnue"
    release_year_str = str(track["release_year"]) if track.get("release_year") else "inconnue"
    album_str = track.get("album_name") or "inconnu"
    duration_ms: Optional[int] = track.get("duration_ms")
    duration_str = f"{duration_ms // 60000}min{(duration_ms % 60000) // 1000}s" if duration_ms else "inconnue"
    explicit_str = "oui" if track.get("explicit") else "non"

    return f"""Tu es un expert en classification musicale. Classe ce titre dans UN genre de la liste ci-dessous.
Si aucun genre ne correspond, réponds uniquement par "aucun".

=== Informations sur le titre ===
Titre : {track['name']}
Artiste(s) : {artists_str}
Album : {album_str} ({release_year_str})
Durée : {duration_str}
Popularité Spotify : {popularity_str}/100
Contenu explicite : {explicit_str}

=== Indices de genre ===
Tags Last.fm de l'artiste : {artist_genres_str}
Tags Last.fm (triés par popularité) : {tags_str}

=== Classification ===
Genres disponibles et leurs mots-clés :
{genres_context}

Liste exacte des genres autorisés : {genres_list}

Réponds UNIQUEMENT avec le nom exact du genre tel qu'il apparaît dans la liste, ou "aucun". Aucune explication."""


def llm_classify(
    groq_client: Groq,
    track: dict,
    available_genres: list[str],
    lastfm_tags: list[str],
    genre_rules: dict,
) -> Optional[str]:
    """
    Classifie via Groq llama-3.1-8b-instant.
    Retourne un genre de la liste ou None si aucun ne convient.
    """
    prompt = build_llm_prompt(track, available_genres, lastfm_tags, genre_rules)
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=20,
        temperature=0.1,
    )
    result = response.choices[0].message.content.strip().strip('"').strip("'")
    return None if result.lower() == "aucun" else result


def fetch_lastfm_tags(artist: str, title: str) -> list[str]:
    """Retourne les top tags Last.fm pour un titre (vide si API non configurée ou erreur)."""
    if not LASTFM_API_KEY:
        return []
    try:
        response = requests.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "track.getTopTags",
                "artist": artist,
                "track": title,
                "api_key": LASTFM_API_KEY,
                "format": "json",
            },
            timeout=5,
        )
        tags = response.json().get("toptags", {}).get("tag", [])
        tags_sorted = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)
        return [t["name"].lower() for t in tags_sorted[:15]]
    except Exception:
        return []


def classify_track(
    track: dict,
    groq_client: Groq,
    available_genres: list[str],
    genre_rules: dict,
    stats: dict,
) -> Optional[tuple[str, str]]:
    """Pipeline de classification : règles Last.fm → fallback LLM.
    Retourne (genre, method) ou None si le titre n'a pu être classifié.
    """
    artist_tags = fetch_lastfm_artist_tags(track["artist"])
    tags = fetch_lastfm_tags(track["artist"], track["name"])

    # 1. Classification par règles (tags Last.fm — sans appel LLM)
    genre = rule_based_classify(artist_tags, tags, genre_rules)
    if genre is not None:
        stats["lastfm_classified"] += 1
        log.info(
            f"  [rules] '{track['artist']} — {track['name']}' → {genre} "
            f"(artist_tags: {artist_tags[:3]}, track_tags: {tags[:3]})"
        )
        return (genre, "lastfm")

    # 2. Fallback LLM si les règles sont insuffisantes
    track_enriched = {**track, "artist_genres": artist_tags}
    stats["llm_classified"] += 1
    genre = llm_classify(groq_client, track_enriched, available_genres, tags, genre_rules)
    log.info(
        f"  [llm] '{track['artist']} — {track['name']}' → {genre or 'aucun'} "
        f"(artist_tags: {artist_tags[:3]}, track_tags: {tags[:3]})"
    )
    return (genre, "llm") if genre is not None else None


# ---------------------------------------------------------------------------
# Logging / rapport
# ---------------------------------------------------------------------------

def generate_run_report(
    run_datetime: str,
    stats: dict,
    classifications: list[dict],
    new_genres: list[str] = [],
) -> str:
    lines = [
        f"# Run du {run_datetime}",
        "",
        "## Résumé",
        "",
        "| Métrique | Valeur |",
        "|----------|--------|",
        f"| Titres traités | {stats['total']} |",
        f"| Ajoutés aux playlists | {stats['added']} |",
        f"| Ignorés | {stats['skipped']} |",
        f"| Classifiés par Last.fm | {stats['lastfm_classified']} |",
        f"| Classifiés par LLM | {stats['llm_classified']} |",
        f"| Nouvelles playlists créées | {stats['new_playlists']} |",
        "",
    ]

    if new_genres:
        lines += [
            "## Nouveaux genres découverts cette session",
            "",
        ] + [f"- `{g}`" for g in new_genres] + [""]

    if classifications:
        lines += [
            "## Détail des classifications",
            "",
            "| Titre | Artiste | Genre |",
            "|-------|---------|-------|",
        ]
        for c in classifications:
            lines.append(f"| {c['name']} | {c['artist']} | {c['genre']} |")
        lines.append("")

    return "\n".join(lines)


def update_history(report: str, run_datetime: str) -> None:
    """Prepend le rapport dans HISTORY.md et écrit le fichier de log du jour."""
    # Log individuel
    LOGS_DIR.mkdir(exist_ok=True)
    log_filename = run_datetime.replace(" ", "_").replace(":", "-")
    log_file = LOGS_DIR / f"{log_filename}.md"
    log_file.write_text(report)

    # HISTORY.md — le plus récent en premier
    separator = "\n---\n\n"
    if HISTORY_PATH.exists():
        existing = HISTORY_PATH.read_text()
        HISTORY_PATH.write_text(report + separator + existing)
    else:
        HISTORY_PATH.write_text(report)

    log.info(f"Logs écrits : logs/{log_filename}.md + HISTORY.md")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== Spotify Sorter — démarrage ===")
    run_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    config = load_config()
    state = load_state()
    genre_rules: dict = config.get("genres", {})
    available_genres = list(genre_rules.keys())

    sp = get_spotify_client()
    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

    log.info("Synchronisation des playlists existantes…")
    existing = fetch_existing_playlists(sp)
    state.setdefault("playlist_ids", {}).update(existing)
    log.info(f"{len(existing)} playlists existantes chargées")

    stats = {
        "total": 0,
        "added": 0,
        "skipped": 0,
        "lastfm_classified": 0,
        "llm_classified": 0,
        "new_playlists": 0,
    }
    classifications: list[dict] = []
    already_classified: set = set(state.get("classified_track_ids", []))

    # 1. Fetch nouveaux likes
    last_id = state.get("last_processed_id")
    log.info(f"Dernier ID traité : {last_id or 'aucun (premier run)'}")
    tracks = fetch_new_liked_tracks(sp, last_id)
    if MAX_TRACKS:
        tracks = tracks[-MAX_TRACKS:]
        log.info(f"{len(tracks)} nouveaux titres à traiter (limité aux {MAX_TRACKS} plus anciens)")
    else:
        log.info(f"{len(tracks)} nouveaux titres à traiter")

    if not tracks:
        log.info("Rien de nouveau. Fin du run.")
        update_history(
            generate_run_report(run_datetime, stats, classifications),
            run_datetime,
        )
        return

    stats["total"] = len(tracks)

    # 2. Classification + ajout dans playlists
    playlist_buckets: dict[str, list[str]] = {}  # genre → [track_ids]
    new_last_id = tracks[0]["id"]  # le plus récent

    for track in tracks:
        if track["id"] in already_classified:
            stats["skipped"] += 1
            continue

        result = classify_track(
            track=track,
            groq_client=groq_client,
            available_genres=available_genres,
            genre_rules=genre_rules,
            stats=stats,
        )

        if result is None:
            log.info(f"  '{track['name']}' — genre non identifié, ignoré")
            stats["skipped"] += 1
            already_classified.add(track["id"])
            continue

        genre, method = result
        playlist_buckets.setdefault(genre, []).append(track["id"])
        classifications.append({
            "name": track["name"],
            "artist": track["artist"],
            "genre": genre,
            "method": method,
        })

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
    new_genres = [g for g in playlist_buckets if g not in list(genre_rules.keys())]
    report = generate_run_report(run_datetime, stats, classifications, new_genres)
    update_history(report, run_datetime)

    log.info("=== Run terminé ===")
    log.info(
        f"Traités: {stats['total']} | "
        f"Ajoutés: {stats['added']} | "
        f"Ignorés: {stats['skipped']} | "
        f"Nouvelles playlists: {stats['new_playlists']}"
    )


if __name__ == "__main__":
    main()
