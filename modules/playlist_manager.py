import sqlite3
import os

class PlaylistManager:
    def __init__(self, db_path="/mnt/denon/Engine Library/Database2/m.db"):
        self.db_path = db_path

    def _get_column_name(self, cur):
        """Erkennt automatisch, ob die DB 'playlistId' oder 'listId' nutzt."""
        cur.execute("PRAGMA table_info(PlaylistEntity)")
        cols = [r[1] for r in cur.fetchall()]
        return "playlistId" if "playlistId" in cols else "listId"

    def get_all_playlists(self):
        """Halt wirklich ALLE Playlisten vom Stick, egal in welchem Ordner."""
        if not os.path.exists(self.db_path): return []
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            # Wir entfernen 'parentListId = 0', um alles zu sehen
            cur.execute("SELECT id, title FROM Playlist ORDER BY title ASC")
            return cur.fetchall()
        except: return []
        finally: conn.close()

    def delete_multiple_playlists(self, playlist_ids):
        """Löscht gewählte IDs und nutzt den korrekten Spaltennamen."""
        if not playlist_ids: return False
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            col = self._get_column_name(cur)
            for pid in playlist_ids:
                # Nutzt die dynamisch erkannte Spalte (playlistId oder listId)
                cur.execute(f"DELETE FROM PlaylistEntity WHERE {col} = ?", (pid,))
                cur.execute("DELETE FROM Playlist WHERE id = ?", (pid,))
            conn.commit()
            self._repair_chain(cur)
            conn.commit()
            return True
        except Exception as e:
            print(f"Löschfehler: {e}")
            return False
        finally: conn.close()

    def _repair_chain(self, cur):
            """Flickt die nextListId-Kette wieder zusammen."""
            cur.execute("SELECT id FROM Playlist ORDER BY id ASC")
            remaining = [r[0] for r in cur.fetchall()]
            
            # --- DER FIX: Kette zuerst komplett trennen ---
            for pid in remaining:
                cur.execute("UPDATE Playlist SET nextListId = NULL WHERE id = ?", (pid,))
                
            # --- Kette sauber neu aufbauen ---
            for i in range(len(remaining)):
                current_id = remaining[i]
                next_id = remaining[i+1] if i < len(remaining) - 1 else 0
                cur.execute("UPDATE Playlist SET nextListId = ? WHERE id = ?", (next_id, current_id))
