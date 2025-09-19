# verify_denon_playlist.py

import sqlite3
import argparse
from pathlib import Path
import os

def main():
    parser = argparse.ArgumentParser(
        description="Überprüft den Inhalt einer Playlist in einer Denon Engine DJ Datenbank (m.db).",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("denon_db", help="Pfad zur 'm.db' Datei auf dem Denon USB-Stick.")
    parser.add_argument("playlist_title", help="Der genaue Name der Playlist, die überprüft werden soll (z.B. 'AI-Set-17-09-2025').")
    args = parser.parse_args()

    db_path = Path(args.denon_db)
    playlist_title = args.playlist_title

    if not db_path.exists():
        print(f"!! FEHLER: Denon Datenbank nicht gefunden unter: {db_path}")
        return

    print("\n" + "="*50)
    print(f"--- DENON PLAYLIST INSPEKTOR ---")
    print("="*50)
    print(f"Suche nach Playlist: '{playlist_title}'")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Finde die Playlist und die ID des ersten Songs in der Kette
        cursor.execute("SELECT id, nextListId FROM Playlist WHERE title = ?", (playlist_title,))
        playlist_data = cursor.fetchone()

        if not playlist_data:
            print(f"\n!! ERGEBNIS: Playlist '{playlist_title}' wurde in der Datenbank nicht gefunden.")
            conn.close()
            return
        
        playlist_id, current_entity_id = playlist_data
        
        if current_entity_id == 0:
            print(f"\n!! ERGEBNIS: Playlist '{playlist_title}' wurde gefunden, ist aber LEER.")
            conn.close()
            return

        print(f"--> Playlist gefunden (ID: {playlist_id}). Lese Track-Liste...")
        print("-" * 50)
        
        track_count = 0
        playlist_tracks = []
        
        # 2. Folge der Kette von PlaylistEntity-Einträgen
        while current_entity_id != 0:
            cursor.execute("SELECT trackId, nextEntityId FROM PlaylistEntity WHERE id = ?", (current_entity_id,))
            entity_data = cursor.fetchone()
            if not entity_data:
                print(f"!! Kette unterbrochen bei Entity ID: {current_entity_id}")
                break
            
            track_id, next_entity_id = entity_data
            
            # 3. Finde den passenden Track-Namen zum Track-ID
            cursor.execute("SELECT path FROM Track WHERE id = ?", (track_id,))
            track_data = cursor.fetchone()
            
            if track_data:
                track_count += 1
                filename = os.path.basename(track_data[0])
                playlist_tracks.append(f"{track_count}. {filename}")
            
            current_entity_id = next_entity_id

        conn.close()
        
        # 4. Gib das Ergebnis aus
        if playlist_tracks:
            print(f"\n✅ ERGEBNIS: Playlist '{playlist_title}' ist GEFÜLLT mit {len(playlist_tracks)} Songs:\n")
            for track in playlist_tracks:
                print(f"   {track}")
        else:
             print(f"\n!! ERGEBNIS: Playlist '{playlist_title}' wurde gefunden, aber es konnten keine Tracks zugeordnet werden.")


    except sqlite3.Error as e:
        print(f"\n!! EIN DATENBANK-FEHLER IST AUFGETRETEN: {e}")

if __name__ == "__main__":
    main()
