"""
Mode debug — Spotify Sorter
============================
Teste toutes les APIs (Spotify, Last.fm, Groq) sur une chanson donnée.
N'écrit rien : pas de state.json, pas de playlist, pas de HISTORY.md, pas de logs fichier.

Usage :
    python3 debug.py                              # utilise le dernier like Spotify
    python3 debug.py "Get Low" "DJ Snake"
    python3 debug.py "Bohemian Rhapsody" "Queen"
"""

import sys
import os
import json
import textwrap
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Imports depuis sorter.py (réutilise les vraies fonctions du pipeline)
# ---------------------------------------------------------------------------
from sorter import (
    get_spotify_client,
    fetch_lastfm_tags,
    rule_based_classify,
    build_llm_prompt,
    extract_remixer,
    _resolve_artist_tags,
    load_config,
    GROQ_MODEL,
)
from groq import Groq

SEP = "─" * 70


def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def ok(label: str, value) -> None:
    print(f"  ✓  {label}: {value}")


def warn(label: str, value) -> None:
    print(f"  ⚠  {label}: {value}")


def fail(label: str, value) -> None:
    print(f"  ✗  {label}: {value}")


# ---------------------------------------------------------------------------
# Recherche du track via Spotify Search ou dernier like
# ---------------------------------------------------------------------------

def search_track(sp, track_name: str, artist_name: str) -> Optional[dict]:
    """Cherche un track par nom+artiste et retourne un dict au format pipeline."""
    query = f"track:{track_name} artist:{artist_name}"
    results = sp.search(q=query, type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    if not items:
        return None
    return _spotify_item_to_track(items[0])


def fetch_latest_liked_track(sp) -> Optional[dict]:
    """Retourne le dernier titre liké."""
    batch = sp.current_user_saved_tracks(limit=1, offset=0)
    items = batch.get("items", [])
    if not items:
        return None
    raw = items[0]["track"]
    if raw is None:
        return None
    return _spotify_item_to_track(raw)


def _spotify_item_to_track(track: dict) -> dict:
    """Convertit un objet track Spotify brut en dict au format pipeline."""
    release_date_raw: str = track.get("album", {}).get("release_date", "") or ""
    release_year: Optional[int] = int(release_date_raw[:4]) if release_date_raw[:4].isdigit() else None
    return {
        "id": track["id"],
        "name": track["name"],
        "artist": track["artists"][0]["name"],
        "artist_id": track["artists"][0]["id"],
        "all_artists": [a["name"] for a in track.get("artists", [])],
        "added_at": None,
        "popularity": track.get("popularity"),
        "duration_ms": track.get("duration_ms"),
        "album_name": track.get("album", {}).get("name"),
        "release_year": release_year,
        "explicit": track.get("explicit", False),
    }


# build_llm_prompt est importé depuis sorter.py — source unique de vérité pour le prompt


# ---------------------------------------------------------------------------
# Validation du prompt
# ---------------------------------------------------------------------------

EXPECTED_SECTIONS = [
    "=== Informations sur le titre ===",
    "Titre :",
    "Artiste(s) :",
    "Album :",
    "Durée :",
    "Popularité Spotify :",
    "Contenu explicite :",
    "=== Indices de genre ===",
    "Tags Last.fm de l'artiste :",
    "Tags Last.fm (triés par popularité) :",
    "=== Classification ===",
    "Genres disponibles et leurs mots-clés :",
    "Liste exacte des genres autorisés :",
    "Réponds UNIQUEMENT",
]

def validate_prompt(prompt: str) -> list[str]:
    """Retourne la liste des éléments attendus mais absents du prompt."""
    return [s for s in EXPECTED_SECTIONS if s not in prompt]


# ---------------------------------------------------------------------------
# Main debug
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "═" * 70)
    print("  SPOTIFY SORTER — MODE DEBUG")
    print("  Aucune écriture : state / playlists / logs intacts")
    print("═" * 70)

    # --- 1. Config ---
    section("1/7 · Chargement de la config")
    config = load_config()
    genre_rules: dict = config.get("genres", {})
    available_genres = list(genre_rules.keys())
    ok("Genres configurés", ", ".join(available_genres))

    # --- 2. Spotify client ---
    section("2/7 · Connexion Spotify")
    try:
        sp = get_spotify_client()
        me = sp.me()
        ok("Authentifié", f"{me['display_name']} ({me['id']})")
    except Exception as e:
        fail("Connexion Spotify", e)
        sys.exit(1)

    # --- 3. Résolution du track ---
    section("3/7 · Résolution du track")
    if len(sys.argv) >= 3:
        track_name, artist_name = sys.argv[1], sys.argv[2]
        print(f"  → Recherche : \"{track_name}\" par \"{artist_name}\"")
        track = search_track(sp, track_name, artist_name)
    else:
        print("  → Aucun argument fourni, utilisation du dernier like Spotify")
        track = fetch_latest_liked_track(sp)

    if track is None:
        fail("Track", "introuvable")
        sys.exit(1)

    ok("Titre",      track["name"])
    ok("Artiste(s)", ", ".join(track["all_artists"]))
    ok("Album",      f"{track['album_name']} ({track['release_year'] or '?'})")
    ok("ID Spotify", track["id"])
    ok("Popularité", f"{track['popularity']}/100" if track["popularity"] is not None else "inconnue")
    duration_ms = track["duration_ms"]
    ok("Durée",      f"{duration_ms // 60000}min{(duration_ms % 60000) // 1000}s" if duration_ms else "inconnue")
    ok("Explicit",   "oui" if track["explicit"] else "non")

    # --- 4. Tags artiste Last.fm ---
    section("4/7 · API Last.fm — artist.getTopTags (remix + multi-artistes)")
    lastfm_key_artist = os.environ.get("LASTFM_API_KEY")
    if not lastfm_key_artist:
        warn("Last.fm artiste", "LASTFM_API_KEY absent — tags ignorés")
        artist_genres = []
    else:
        remixer = extract_remixer(track["name"])
        all_artists = track.get("all_artists") or [track["artist"]]
        if remixer:
            ok("Remix détecté", f"remixeur : {remixer!r} (artiste original ignoré)")
        elif len(all_artists) > 1:
            ok("Multi-artistes", ", ".join(all_artists))
        print(f"  → Appel _resolve_artist_tags()")
        artist_genres = _resolve_artist_tags(track)
        if artist_genres:
            ok("Tags artiste(s) fusionnés", ", ".join(artist_genres))
        else:
            warn("Tags artiste(s)", "aucun tag retourné")
    track["artist_genres"] = artist_genres

    # --- 5. Tags Last.fm ---
    section("5/7 · API Last.fm — track.getTopTags")
    lastfm_key = os.environ.get("LASTFM_API_KEY")
    if not lastfm_key:
        warn("Last.fm", "LASTFM_API_KEY absent — tags ignorés")
        lastfm_tags = []
    else:
        print(f"  → Appel track.getTopTags(artist='{track['artist']}', track='{track['name']}')")
        lastfm_tags = fetch_lastfm_tags(track["artist"], track["name"])
        if lastfm_tags:
            ok("Tags récupérés", f"{len(lastfm_tags)} tags (triés par popularité)")
            for i, tag in enumerate(lastfm_tags, 1):
                print(f"     {i:>2}. {tag}")
        else:
            warn("Tags Last.fm", "aucun tag retourné")

    # --- 6. Classification par règles ---
    section("6/7 · Classification par règles Last.fm")
    rules_genre = rule_based_classify(artist_genres, lastfm_tags, genre_rules)
    if rules_genre is not None:
        ok("Résultat", f"{rules_genre} → LLM court-circuité")
    else:
        warn("Résultat", "aucun match clair → fallback LLM")

    # --- 7. Prompt + Groq ---
    section("7/7 · Groq — Prompt complet + réponse LLM")

    prompt = build_llm_prompt(track, available_genres, lastfm_tags, genre_rules)

    print("\n  ┌─ PROMPT ENVOYÉ AU LLM " + "─" * 46)
    for line in prompt.splitlines():
        print(f"  │ {line}")
    print("  └" + "─" * 68)

    # Validation du prompt
    missing = validate_prompt(prompt)
    print()
    if missing:
        fail("Validation prompt", f"{len(missing)} élément(s) manquant(s) :")
        for m in missing:
            print(f"     ✗ {m!r}")
    else:
        ok("Validation prompt", "toutes les sections attendues sont présentes ✓")

    # Appel Groq
    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        warn("Groq", "GROQ_API_KEY absent — classification ignorée")
    else:
        print(f"\n  → Appel Groq ({GROQ_MODEL}, temperature=0.1, max_tokens=20)")
        try:
            groq_client = Groq(api_key=groq_key)
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
                temperature=0.1,
            )
            raw_result = response.choices[0].message.content.strip().strip('"').strip("'")
            genre = None if raw_result.lower() == "aucun" else raw_result

            print()
            if genre in available_genres:
                ok("Réponse brute LLM", repr(raw_result))
                ok("Genre classifié   ", genre)
            elif genre is None:
                ok("Réponse brute LLM", repr(raw_result))
                warn("Genre classifié   ", "aucun (titre non classifié)")
            else:
                ok("Réponse brute LLM", repr(raw_result))
                warn("Genre classifié   ", f"{genre!r} — hors liste ! (le pipeline créerait une nouvelle playlist)")
        except Exception as e:
            fail("Groq", e)

    print("\n" + "═" * 70)
    print("  DEBUG TERMINÉ — aucune donnée modifiée")
    print("═" * 70 + "\n")


if __name__ == "__main__":
    main()
