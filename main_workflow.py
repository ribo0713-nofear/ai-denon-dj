# main_workflow.py (v19.0 - Final Professional Build)

import os, glob, random, argparse, sys, time, sqlite3, re, librosa, numpy as np, json, aubio, subprocess
import pyloudnorm as pyln
import shutil

# ==============================================================================
#  Werkzeuge
# ==============================================================================
GARBAGE_KEYWORDS = ['official music video','official video','music video','official audio','hd','4k','lyrics','lyric video','extended','original mix','original','feat','ft','audio','visualiser']

def clean_filename(filename):
    name, extension = os.path.splitext(filename)
    name = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}', '', name)
    name = re.sub(r'[\s_-]+[a-zA-Z0-9_-]{11}[\s_]*$', '', name)
    for keyword in GARBAGE_KEYWORDS:
        name = re.sub(r'\b' + re.escape(keyword) + r'\b', '', name, flags=re.IGNORECASE)
    name = name.replace('_', ' ').replace('-', ' - ')
    name = re.sub(r"[^a-zA-Z0-9\s'-]", '', name)
    cleaned_name = " ".join(name.split()).strip()
    return f"{cleaned_name}{extension}" if cleaned_name else filename

def analyze_song(file_path):
    try:
        y, sr = librosa.load(file_path, sr=None, mono=True);
        if np.mean(np.abs(y)) < 0.0001: return None
        duration = librosa.get_duration(y=y, sr=sr); meter = pyln.Meter(sr); loudness = meter.integrated_loudness(y)
        rms = librosa.feature.rms(y=y)[0]; _, beat_times = librosa.beat.beat_track(y=y, sr=sr, units='time')
        mix_in_point = beat_times[0] if beat_times.size > 64 else None; mix_out_point = beat_times[-32] if beat_times.size > 64 else None
        win_s=512; hop_s=win_s//2; tempo_o = aubio.tempo("default", win_s, hop_s, sr); total_frames = 0; aubio_beats = []
        while total_frames + hop_s < len(y):
            samples = y[total_frames : total_frames + hop_s]; is_beat = tempo_o(samples)
            if is_beat: aubio_beats.append(tempo_o.get_last_s())
            total_frames += hop_s
        if len(aubio_beats) > 1: tempo_val = np.median(60. / np.diff(aubio_beats))
        else: tempo_val_res, _ = librosa.beat.beat_track(y=y, sr=sr); tempo_val = tempo_val_res[0] if hasattr(tempo_val_res, "__len__") else tempo_val_res
        chroma = librosa.feature.chroma_stft(y=y, sr=sr); key_map = {'Cmaj':'8B','Dbmaj':'3B','Dmaj':'10B','Ebmaj':'5B','Emaj':'12B','Fmaj':'7B','F#maj':'2B','Gmaj':'9B','Abmaj':'4B','Amaj':'11B','Bbmaj':'6B','Bmaj':'1B','Amin':'8A','Bbmin':'3A','Bmin':'10A','Cmin':'5A','C#min':'12A','Dmin':'7A','D#min':'2A','Emin':'9A','Fmin':'4A','F#min':'11A','Gmin':'6A','G#min':'1A'}; notes=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']; maj_p=np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]); min_p=np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]); chroma_avg = np.mean(chroma, axis=1); best_corr=-1; best_key=None
        for i in range(12):
            for mode, profile in [("maj", maj_p), ("min", min_p)]:
                corr = np.corrcoef(chroma_avg, np.roll(profile, i))[0, 1]
                if corr > best_corr: best_corr, best_key = corr, f"{notes[i]}{mode}"
        key_full, camelot_key = best_key, key_map.get(best_key, None)
        return {'bpm': float(tempo_val), 'key_full': key_full, 'camelot_key': camelot_key, 'energy_avg': float(np.mean(rms)), 'lufs': float(loudness), 'duration': float(duration),'mix_in_point': mix_in_point, 'mix_out_point': mix_out_point}
    except Exception as e: print(f"  !! Kritischer Analyse-Fehler bei {os.path.basename(file_path)}: {e}"); return None

def find_best_successor(current_track, available_tracks, bpm_tolerance, playlist_phase, bpm_range, priority_tracks=[], priority_bonus=3.0):
    WEIGHT_BPM_TOLERANCE = 8.0; WEIGHT_KEY = 3.0; WEIGHT_ENERGY_PROXIMITY = 2.0; WEIGHT_ENERGY_CURVE = 35.0; WEIGHT_BPM_CURVE = 10.0
    scored_songs = []; min_bpm, max_bpm = bpm_range; priority_ids = {p['id'] for p in priority_tracks}
    bpm_third = (max_bpm - min_bpm) / 3 if (max_bpm - min_bpm) > 0 else 1
    target_bpm_map = {"warmup": (min_bpm, min_bpm + bpm_third), "peak": (min_bpm + bpm_third, max_bpm), "cooldown": (min_bpm, min_bpm + bpm_third * 1.5)}
    target_energy_map = {"warmup": (1, 5), "peak": (6, 10), "cooldown": (1, 5)}
    def calculate_key_score(c1, c2):
        if not c1 or not c2: return 0
        try: n1, l1 = int(c1[:-1]), c1[-1]; n2, l2 = int(c2[:-1]), c2[-1]
        except (ValueError, TypeError): return 0
        if n1 == n2: return 15 if l1 == l2 else 12
        is_next = n2 == (n1 % 12) + 1; is_prev = n2 == (n1 - 2 + 12) % 12 + 1
        if l1 == l2 and (is_next or is_prev): return 10
        return 0
    def calculate_bpm_score(bpm1, bpm2, tolerance):
        if not bpm1 or not bpm2 or bpm1 == 0 or bpm2 == 0: return 0
        bpm1, bpm2 = float(bpm1), float(bpm2)
        if abs(bpm1 - bpm2) <= bpm1 * tolerance: return 10
        if abs(bpm1 * 2 - bpm2) <= (bpm1 * 2) * tolerance: return 8
        if abs(bpm1 / 2 - bpm2) <= (bpm1 / 2) * tolerance: return 8
        return 0
    for song in available_tracks:
        bpm_tol_s = calculate_bpm_score(current_track['bpm'], song['bpm'], bpm_tolerance)
        if bpm_tol_s == 0: continue
        target_min_bpm, target_max_bpm = target_bpm_map[playlist_phase]
        bpm_curve_s = 10 if target_min_bpm <= song['bpm'] <= target_max_bpm else max(0, 5 - (min(abs(song['bpm'] - target_min_bpm), abs(song['bpm'] - target_max_bpm)) / bpm_third) * 5)
        key_s = calculate_key_score(current_track['camelot_key'], song['camelot_key'])
        energy_prox_s = max(0, 10 - abs(current_track['energy_norm'] - song['energy_norm']))
        target_min_en, target_max_en = target_energy_map[playlist_phase]
        energy_curve_s = 10 if target_min_en <= song['energy_norm'] <= target_max_en else 5 - min(abs(song['energy_norm'] - target_min_en), abs(song['energy_norm'] - target_max_en))
        total_s = (bpm_tol_s * WEIGHT_BPM_TOLERANCE) + (key_s * WEIGHT_KEY) + (energy_prox_s * WEIGHT_ENERGY_PROXIMITY) + (energy_curve_s * WEIGHT_ENERGY_CURVE) + (bpm_curve_s * WEIGHT_BPM_CURVE)
        if song['id'] in priority_ids: total_s *= priority_bonus
        if total_s > 0: scored_songs.append((song, total_s))
    return sorted(scored_songs, key=lambda item: item[1], reverse=True)

def find_best_dramaturgy(all_tracks, bpm_tolerance, target_length, max_start_energy, anchor_tracks=[]):
    best_playlist = []; best_score = -1
    all_bpms = [t['bpm'] for t in all_tracks if t.get('bpm')]; 
    if not all_bpms: return []
    bpm_range = (min(all_bpms), max(all_bpms))
    print(f"--> Globaler BPM-Bereich der Bibliothek: {bpm_range[0]:.2f} - {bpm_range[1]:.2f}")
    start_candidates = [t for t in all_tracks if t.get('energy_norm') is not None and t['energy_norm'] <= max_start_energy]
    if not start_candidates: 
        print(f"\nWARNUNG: Keine Start-Kandidaten mit Energie <= {max_start_energy} gefunden. Nutze alle Tracks."); 
        start_candidates = all_tracks
    random.shuffle(start_candidates)
    
    for i, start_track in enumerate(start_candidates[:20]):
        print(f"--> Teste Dramaturgie-Pfad {i+1}/{min(len(start_candidates), 20)} (Start: {clean_filename(start_track['filename'])})")
        current_playlist = [start_track]; available_tracks = [t for t in all_tracks if t['id'] != start_track['id']]; current_track = start_track
        playlist_score = 0
        while len(current_playlist) < target_length:
            if not available_tracks: break
            progress = len(current_playlist) / target_length
            phase = "warmup" if progress < 0.25 else ("peak" if progress < 0.75 else "cooldown")
            pending_anchors = [p for p in anchor_tracks if p['id'] not in {t['id'] for t in current_playlist}]
            successors = find_best_successor(current_track, available_tracks, bpm_tolerance, phase, bpm_range, priority_tracks=pending_anchors)
            if not successors: break
            next_track, score = successors[0]
            playlist_score += score
            current_playlist.append(next_track); available_tracks = [t for t in available_tracks if t['id'] != next_track['id']]; current_track = next_track
        
        pending_anchors = [p for p in anchor_tracks if p['id'] not in {t['id'] for t in current_playlist}]
        for anchor in pending_anchors:
            if len(current_playlist) >= target_length: current_playlist.pop(random.randint(1, len(current_playlist)-1))
            current_playlist.append(anchor)

        avg_score = playlist_score / len(current_playlist) if current_playlist else 0
        if len(current_playlist) > len(best_playlist) or (len(current_playlist) == len(best_playlist) and avg_score > best_score):
            best_playlist = list(current_playlist); best_score = avg_score
            print(f"    ==> Neue beste Playlist gefunden! Länge: {len(best_playlist)}, Score: {avg_score:.2f}")
    return best_playlist

def main():
    parser = argparse.ArgumentParser(description="KI-DJ Master Suite (Final)", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("music_folder", help="Pfad zum Musikordner.")
    parser.add_argument("output_name", help="Name für den Ergebnisordner/Playlist.")
    parser.add_argument("--length", type=int, default=40, help="Die Ziel-Länge der Playlist.")
    parser.add_argument("--bpm-tolerance", type=float, default=0.02, help="Maximale prozentuale BPM-Abweichung (z.B. 0.02 für 2%%).")
    parser.add_argument("--max-start-energy", type=float, default=4.0, help="Maximale normalisierte Energie (1-10) für den Start-Track.")
    parser.add_argument('--anker', action='append', help='Teil des Dateinamens eines Tracks, der enthalten sein muss. Mehrfach verwendbar.')
    parser.add_argument("--force-rescan", action="store_true", help="Erzwingt eine komplette Neu-Bereinigung und Neu-Analyse.")
    parser.add_argument("--denon-db-path", help="Optional: Pfad zur 'm.db' auf dem Denon Stick, um den Import automatisch zu starten.")
    args = parser.parse_args()
    
    # --- Schritt 1: Bereinigen & De-Duplizieren ---
    clean_marker_path = os.path.join(args.music_folder, ".dj_cleaned")
    run_cleaning = True
    if os.path.exists(clean_marker_path) and not args.force_rescan:
        if input(f"INFO: Ordner scheint bereinigt. Bereinigung überspringen? (j/n): ").lower() == 'j':
            run_cleaning = False
    if run_cleaning:
        clean_and_deduplicate_folder(args.music_folder)

    # --- Schritt 2: Datenbank & Analyse ---
    db_path = os.path.join(os.path.dirname(args.music_folder.rstrip('/')), "ki_dj_library.db")
    run_analysis = True
    if os.path.exists(db_path) and not args.force_rescan:
        conn_check = sqlite3.connect(db_path)
        try:
            columns = [info[1] for info in conn_check.execute("PRAGMA table_info(songs)").fetchall()]
            if 'energy_norm' not in columns or 'relative_path' not in columns:
                print("\n!! WICHTIG: Deine 'ki_dj_library.db' ist veraltet. Eine Neu-Analyse ist erforderlich.");
                run_analysis = True
            else:
                if input(f"INFO: DB ist aktuell. Analyse überspringen? (j/n): ").lower() == 'j':
                    run_analysis = False
        finally:
            conn_check.close()
    
    if run_analysis:
        print("\nINFO: Schritt 2/5 - Erstelle/Aktualisiere KI-Datenbank...")
        if args.force_rescan and os.path.exists(db_path): os.remove(db_path)
        conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS songs (id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE, filename TEXT NOT NULL, bpm REAL, key_full TEXT, camelot_key TEXT, energy_avg REAL, lufs REAL, duration REAL, mix_in_point REAL, mix_out_point REAL, energy_norm REAL)""")
        all_music_files = [p for ext in ['*.mp3','*.wav','*.flac','*.aiff'] for p in glob.glob(os.path.join(args.music_folder, '**', ext), recursive=True)]
        db_paths = {row['relative_path'] for row in conn.execute("SELECT relative_path FROM songs").fetchall()}
        files_to_scan = [f for f in all_music_files if os.path.relpath(f, args.music_folder).replace('\\','/') not in db_paths]
        print(f"{len(files_to_scan)} neue/geänderte Songs zu analysieren.")
        for i, file_path in enumerate(files_to_scan):
            print(f"({i+1}/{len(files_to_scan)}) Analysiere: {os.path.basename(file_path)}")
            features = analyze_song(file_path)
            if features:
                features['relative_path'] = os.path.relpath(file_path, args.music_folder).replace('\\', '/'); features['filename'] = os.path.basename(file_path)
                conn.execute("""INSERT OR REPLACE INTO songs (relative_path, filename, bpm, key_full, camelot_key, energy_avg, lufs, duration, mix_in_point, mix_out_point) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (features['relative_path'],features['filename'],features['bpm'],features['key_full'],features['camelot_key'],features['energy_avg'],features['lufs'], features['duration'],features['mix_in_point'], features['mix_out_point']))
        conn.commit()
        tracks = conn.execute("SELECT rowid as id, energy_avg FROM songs WHERE energy_avg IS NOT NULL").fetchall()
        if tracks:
            energies = [t['energy_avg'] for t in tracks]; min_energy, max_energy = min(energies), max(energies)
            for track in tracks:
                norm_energy = 1 + 9 * (track['energy_avg'] - min_energy) / (max_energy - min_energy) if (max_energy - min_energy) > 0 else 5
                conn.execute("UPDATE songs SET energy_norm = ? WHERE rowid = ?", (norm_energy, track['id']))
            conn.commit()
        conn.close()
        print("--> Analyse & Energie-Normalisierung abgeschlossen.")
    else:
        print("\nINFO: Schritt 2/5 - Analyse wird übersprungen.")

    # --- Schritt 3: Playlist-Erstellung ---
    print("\nINFO: Schritt 3/5 - Suche die dramaturgisch beste Playlist...")
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    all_tracks = [dict(row) for row in conn.execute("SELECT *, rowid as id FROM songs WHERE bpm IS NOT NULL AND camelot_key IS NOT NULL AND energy_norm IS NOT NULL").fetchall()]
    conn.close()
    anchor_tracks = []
    if args.anker:
        for anker_name in args.anker:
            found = next((track for track in all_tracks if anker_name.lower() in track['filename'].lower()), None)
            if found: anchor_tracks.append(found); print(f"--> Anker-Track gefunden: '{found['filename']}'")
            else: print(f"WARNUNG: Anker-Track für '{anker_name}' nicht gefunden.")
    final_playlist = find_best_dramaturgy(all_tracks, args.bpm_tolerance, args.length, args.max_start_energy, anchor_tracks)
    if not final_playlist: print("\nFEHLER: Konnte keine funktionierende Playlist erstellen."); return

    # --- Schritt 4: Output & Paketierung ---
    output_folder = args.output_name
    print(f"\nINFO: Schritt 4/5 - Erstelle Output-Dateien im Ordner '{output_folder}'...")
    if not os.path.exists(output_folder): os.makedirs(output_folder)
    
    base_filename = f"{args.output_name}_{len(final_playlist)}songs"
    txt_filepath = os.path.join(output_folder, f"{base_filename}_set_report.txt")
    m3u_filepath = os.path.join(output_folder, f"{base_filename}_portable.m3u")
    live_folder_path = os.path.join(output_folder, "Live-Set")
    if not os.path.exists(live_folder_path): os.makedirs(live_folder_path)

    with open(txt_filepath, 'w', encoding='utf-8') as f:
        f.write(f"--- KI-Set-Report '{args.output_name}' ({len(final_playlist)} Songs) ---\n\n")
        if final_playlist:
            max_len = max(len(clean_filename(t['filename'])) for t in final_playlist)
            header = f"{'Nr.':<4}{'Song':<{max_len + 2}}{'BPM':<10}{'Energie':<12}{'Tonart':<9}{'Mix-OUT':<11}{'Denon Anzeige'}\n"
            f.write(header); f.write('-' * (len(header) - 1) + '\n')
            for j, track in enumerate(final_playlist):
                song_name = clean_filename(track['filename']); bpm_str = f"{track['bpm']:.2f}"; energy_str = f"{track['energy_norm']:.1f}/10"; key_str = track['camelot_key'] or 'N/A'
                mix_out_str = "N/A"; denon_display_str = "N/A"
                out_point, duration = track.get('mix_out_point'), track.get('duration')
                if out_point is not None and duration is not None:
                    out_min, out_sec = divmod(int(out_point), 60); mix_out_str = f"{out_min:02d}:{out_sec:02d}"
                    remaining_sec = int(duration - out_point); rem_min, rem_sec = divmod(remaining_sec, 60); denon_display_str = f"-{rem_min:02d}:{rem_sec:02d}"
                f.write(f"{str(j+1)+'.':<4}{song_name:<{max_len + 2}}{bpm_str:<10}{energy_str:<12}{key_str:<9}{mix_out_str:<11}{denon_display_str}\n")
    print(f"--> Set-Report als Tabelle in '{os.path.basename(txt_filepath)}' gespeichert.")

    with open(m3u_filepath, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        for track in final_playlist:
            source_path = os.path.join(args.music_folder, track['relative_path'])
            dest_path = os.path.join(live_folder_path, track['filename'])
            if os.path.exists(source_path) and not os.path.exists(dest_path): shutil.copy2(source_path, dest_path)
            f.write(os.path.join("Live-Set", track['filename']).replace('\\', '/') + '\n')
    print(f"--> Portable USB-Playlist in '{os.path.basename(m3u_filepath)}' gespeichert.")
    
    print("\n" + "="*50); print("--- WORKFLOW ABGESCHLOSSEN ---"); print("="*50)
    print("Dein fertiges Set-Paket ist bereit:")
    print(f"  -> Set-Report:       {os.path.abspath(txt_filepath)}")
    print(f"  -> M3U für Import:   {os.path.abspath(m3u_filepath)}")
    print(f"  -> Audio-Ordner:     {os.path.abspath(live_folder_path)}")

    # --- Schritt 5: Automatischer Denon DB Import ---
    if args.denon_db_path:
        importer_script_path = "denon_importer.py"
        if not os.path.exists(importer_script_path):
            print(f"\n!! FEHLER: Das Importer-Skript '{importer_script_path}' wurde nicht im selben Verzeichnis gefunden."); return
        if not os.path.exists(args.denon_db_path):
            print(f"\n!! FEHLER: Der angegebene Pfad zur Denon DB '{args.denon_db_path}' ist ungültig."); return
        print("\nINFO: Schritt 5/5 - Starte den automatischen Import in die Denon-Datenbank...")
        try:
            command = [sys.executable, importer_script_path, m3u_filepath, args.denon_db_path]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None: break
                if output: print(f"  [Importer] > {output.strip()}")
            if process.poll() == 0:
                print("\n--- IMPORT ERFOLGREICH IN DENON DB INTEGRIERT ---")
            else:
                print("\n!! FEHLER: Der Denon DB Import ist fehlgeschlagen.")
        except Exception as e:
            print(f"\n!! FEHLER beim Starten des Importers: {e}")

if __name__ == "__main__":
    main()
