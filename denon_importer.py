# denon_importer.py (v5.0 - Final & Stable)

import sqlite3
import argparse
import shutil
from datetime import datetime
from pathlib import Path
import sys
import os

def backup_db(db_path):
    """Erstellt eine Sicherheitskopie der Datenbankdatei, aber nur, wenn noch keine existiert."""
    backup_path = db_path.with_suffix('.db.backup')
    if backup_path.exists():
        print(f"--> Vorhandene Sicherheitskopie gefunden: {backup_path.name}.")
        return True
    try:
        shutil.copyfile(db_path, backup_path)
        print(f"--> Neue Sicherheitskopie erstellt: {backup_path.name}")
        return True
    except Exception as e:
        print(f"!! FEHLER: Konnte keine Sicherheitskopie erstellen: {e}")
        return False

def read_playlist_file(playlist_path):
    """Liest die relativen Pfade aus einer .m3u Playlist-Datei."""
    if not playlist_path.exists():
        print(f"!! FEHLER: Playlist-Datei nicht gefunden: {playlist_path}")
        return []
    with open(playlist_path, 'r', encoding='utf-8') as f:
        track_paths = [line.strip() for line in f if not line.startswith('#') and line.strip()]
    print(f"--> {len(track_paths)} Tracks aus der Playlist-Datei gelesen.")
    return track_paths

def verify_import(cursor, playlist_id, expected_count):
    """Überprüft, ob die Anzahl der Tracks in der DB mit der erwarteten Anzahl übereinstimmt."""
    print("--> Starte Verifizierung des Imports...")
    cursor.execute("SELECT count(*) FROM PlaylistEntity WHERE listId = ?", (playlist_id,))
    actual_count = cursor.fetchone()[0]
    if actual_count == expected_count and expected_count > 0:
        print(f"--> Verifizierung ERFOLGREICH: {actual_count} von {expected_count} Tracks wurden in der Playlist in der Datenbank gefunden.")
        return True
    else:
        print(f"!! Verifizierung FEHLGESCHLAGEN: Erwartet wurden {expected_count} Tracks, aber nur {actual_count} in der DB gefunden.")
        return False

def main():
    parser = argparse.ArgumentParser(description="Importiert eine KI-generierte Playlist in eine Denon Engine DJ Datenbank (m.db).")
    parser.add_argument("playlist_file", help="Pfad zur '_portable.m3u' Playlist-Datei.")
    parser.add_argument("denon_db", help="Pfad zur 'm.db' Datei auf dem Denon USB-Stick.")
    args = parser.parse_args()

    playlist_path = Path(args.playlist_file)
    db_path = Path(args.denon_db)

    if not db_path.exists():
        print(f"!! FEHLER: Denon Datenbank nicht gefunden unter: {db_path}")
        return

    print("\n" + "="*50)
    print("--- STARTE DENON PLAYLIST IMPORTER (v5.0 Stable) ---")
    print("="*50)

    if not backup_db(db_path):
        return

    track_relative_paths = read_playlist_file(playlist_path)
    if not track_relative_paths:
        return
        
    playlist_title = datetime.now().strftime("AI-Set-%d-%m-%Y")
    current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"--> Erstelle Playlist mit dem Namen: '{playlist_title}'")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print(f"--> Räume auf: Lösche alte Playlist '{playlist_title}', falls vorhanden...")
        cursor.execute("DELETE FROM Playlist WHERE title = ?", (playlist_title,))

        # KORREKTE INSERT-Anweisung, basierend auf Ihrer funktionierenden Version
        cursor.execute("""
            INSERT INTO Playlist (title, parentListId, isPersisted, lastEditTime, nextListId, isExplicitlyExported) 
            VALUES (?, 0, 1, ?, 0, 0)
            """, (playlist_title, current_timestamp))
        new_playlist_id = cursor.lastrowid
        print(f"--> Neue Playlist in DB erstellt mit ID: {new_playlist_id}")

        track_ids_in_order = []
        print("--> Suche Tracks in der Denon-Datenbank...")
        for rel_path in track_relative_paths:
            filename = os.path.basename(rel_path)
            cursor.execute("SELECT id FROM Track WHERE path LIKE ?", ('%/' + filename,))
            result = cursor.fetchone()
            if result:
                track_ids_in_order.append(result[0])
            else:
                print(f"    !! WARNUNG: Track '{filename}' konnte nicht gefunden werden. Wird übersprungen.")
        
        expected_track_count = len(track_ids_in_order)
        if not track_ids_in_order:
            print("\n!! FEHLER: Es konnten keine Tracks in der Datenbank gefunden werden. Import wird abgebrochen.")
            conn.close()
            return

        print("--> Baue die finale Track-Kette auf...")
        next_entity_id = 0
        first_entity_id = 0
        
        db_uuid_result = cursor.execute("SELECT uuid FROM Information LIMIT 1").fetchone()
        db_uuid = db_uuid_result[0] if db_uuid_result else None

        for track_id in reversed(track_ids_in_order):
            cursor.execute("""
                INSERT INTO PlaylistEntity (listId, trackId, nextEntityId, databaseUuid, membershipReference) 
                VALUES (?, ?, ?, ?, 0)
                """, (new_playlist_id, track_id, next_entity_id, db_uuid))
            next_entity_id = cursor.lastrowid
            first_entity_id = next_entity_id
        
        if first_entity_id != 0:
            print(f"--> Setze Anker: Verknüpfe Playlist (ID: {new_playlist_id}) mit dem ersten Track...")
            cursor.execute("UPDATE Playlist SET nextListId = ? WHERE id = ?", (first_entity_id, new_playlist_id))

        if not verify_import(cursor, new_playlist_id, expected_track_count):
            conn.rollback()
            print("!! Import wurde aufgrund eines Verifizierungs-Fehlers rückgängig gemacht.")
        else:
            conn.commit()
            print("\n" + "="*50)
            print("--- IMPORT ERFOLGREICH ABGESCHLOSSEN & VERIFIZIERT ---")
            print("="*50)
            print("Sie können den USB-Stick jetzt sicher entfernen und am Denon Prime Go+ testen.")

        conn.close()
        
    except sqlite3.Error as e:
        print(f"\n!! EIN SCHWERWIEGENDER DATENBANK-FEHLER IST AUFGETRETEN: {e}")
        print("!! Die Original-Datenbank ist sicher. Bitte stellen Sie sie aus dem .backup wieder her.")

if __name__ == "__main__":
    main()
