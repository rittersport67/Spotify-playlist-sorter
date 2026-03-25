"""
Script d'authentification initiale Spotify.
À exécuter UNE SEULE FOIS en local pour générer le refresh token.

Usage :
    SPOTIFY_CLIENT_ID=xxx SPOTIFY_CLIENT_SECRET=yyy SPOTIFY_REDIRECT_URI=zzz python auth_setup.py

Le fichier .spotify_cache généré contient le refresh token.
Son contenu doit être copié dans le secret GitHub SPOTIFY_CACHE.
"""

import os
from pathlib import Path
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

load_dotenv()


SCOPE = (
    "user-library-read "
    "playlist-read-private "
    "playlist-modify-private "
    "playlist-modify-public"
)

CACHE_PATH = Path(".spotify_cache")

def main():
    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=os.environ["SPOTIFY_CLIENT_ID"],
            client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
            redirect_uri=os.environ["SPOTIFY_REDIRECT_URI"],
            scope=SCOPE,
            cache_path=CACHE_PATH,
            open_browser=True,
        )
    )

    user = sp.current_user()
    print(f"\n✅ Authentifié en tant que : {user['display_name']} ({user['id']})")
    print(f"✅ Cache écrit dans : {CACHE_PATH.resolve()}")

    cache_content = CACHE_PATH.read_text()
    print("\n--- Contenu à copier dans le secret GitHub SPOTIFY_CACHE ---")
    print(cache_content)
    print("--------------------------------------------------------------")
    print("\nÉtapes suivantes :")
    print("1. Copie le JSON ci-dessus dans Settings > Secrets > SPOTIFY_CACHE")
    print("2. Ajoute aussi SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI, GROQ_API_KEY")
    print("3. Lance le workflow depuis l'onglet Actions pour tester\n")

if __name__ == "__main__":
    main()
