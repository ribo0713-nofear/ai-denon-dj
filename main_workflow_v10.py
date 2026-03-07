import os
import glob
import argparse
import sys
import sqlite3
import re
import subprocess
import shutil
import time
import warnings
import uuid
from datetime import datetime
from modules.smart_usb_mount import SmartUSBMount
from modules.playlist_manager import PlaylistManager

# --- SETTINGS ---
MOUNT_TARGET = "/mnt/denon"
DENON_DB_REL_PATH = "Engine Library/Database2/m.db" 

# Warnungen unterdrücken
warnings.filterwarnings("ignore", category=DeprecationWarning)

# --- PDF MODUL ---
PDF_AVAILABLE = False
try:
    from fpdf import FPDF
    PDF_AVAILABLE = True
except ImportError:
    print("[SYSTEM] Warnung: 'fpdf' Modul fehlt. Kein PDF Export.", flush=True)

# --- ANALYSE MODUL ---
try:
    from modules.analysis_engine_v3 import analyze_song
except ImportError:
    print("[SYSTEM] Warnung: 'modules' Ordner fehlt.", flush=True)


# ==========================================
# 1. HELPER
# ==========================================
def translate_key_to_camelot(key_str):
    if not key_str or key_str == '-': return "-"
    k = key_str.replace(" ", "").lower()
    mapping = {
        'abm': '1A', 'g#m': '1A', 'abmin': '1A', 'ebm': '2A', 'd#m': '2A', 'ebmin': '2A',
        'bbm': '3A', 'a#m': '3A', 'bbmin': '3A', 'a#min': '3A', 'fm': '4A',  'fmin': '4A',
        'cm': '5A',  'cmin': '5A', 'gm': '6A',  'gmin': '6A', 'dm': '7A',  'dmin': '7A',
        'am': '8A',  'amin': '8A', 'em': '9A',  'emin': '9A', 'bm': '10A', 'bmin': '10A',
        'f#m': '11A', 'gbm': '11A', 'f#min': '11A', 'c#m': '12A', 'dbm': '12A', 'c#min': '12A',
        'b': '1B', 'bmaj': '1B', 'f#': '2B', 'gb': '2B', 'f#maj': '2B', 'db': '3B', 'c#': '3B', 
        'dbmaj': '3B', 'ab': '4B', 'g#': '4B', 'abmaj': '4B', 'eb': '5B', 'ebmaj': '5B', 
        'bb': '6B', 'a#': '6B', 'bbmaj': '6B', 'f': '7B', 'fmaj': '7B', 'c': '8B', 'cmaj': '8B',
        'g': '9B', 'gmaj': '9B', 'd': '10B', 'dmaj': '10B', 'a': '11B', 'amaj': '11B', 
        'e': '12B', 'emaj': '12B'
    }
    if k in mapping: return mapping[k]
    if re.match(r"^\d{1,2}[ab]$", k): return k.upper()
    return key_str 

def recalibrate_playlist_energy(playlist):
    if not playlist: return playlist
    raw_values = [t.get('energy_avg', 0.1) or 0.1 for t in playlist]
    max_val = max(raw_values)
    if max_val < 0.05: max_val = 1.0 
    scale_factor = 9.5 / max_val
    for t in playlist:
        raw = t.get('energy_avg', 0.1) or 0.1
        new_nrg = int(raw * scale_factor)
        t['nrg_display'] = max(2, min(10, new_nrg))
    return playlist

def calculate_smart_cues(bpm, duration, first_downbeat, energy_display):
    if not bpm or bpm < 10: return 0.0, duration - 10
    sec_per_beat = 60 / bpm
    if first_downbeat and first_downbeat > 2.0:
        cue_in = first_downbeat
    else:
        if energy_display < 6: cue_in = sec_per_beat * 64
        else: cue_in = sec_per_beat * 32
    mix_out = duration - (sec_per_beat * 32)
    if mix_out < cue_in + 20: mix_out = duration - 15 
    return cue_in, mix_out

def aggressive_clean_name(filename):
    name = re.sub(r'\[.*?\]', '', filename)
    name = re.sub(r'\(.*?\)', '', name)
    name = os.path.splitext(name)[0].replace('_', ' ')
    return " ".join(name.split())

def fmt_time(sec):
    if sec is None: return "0:00"
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m}:{s:02d}"

# ==========================================
# 2. PDF GENERATOR
# ==========================================
class PDFReport(FPDF):
    def set_report_title(self, title):
        self.report_title = title

    def header(self):
        self.set_font('Arial', 'B', 16)
        title_text = getattr(self, 'report_title', 'AI DJ REPORT')
        self.cell(0, 10, title_text, 0, 1, 'C')
        self.ln(5)
        self.set_fill_color(0, 0, 100)
        self.set_text_color(255, 255, 255)
        self.set_font('Arial', 'B', 10)
        self.cols = [15, 110, 15, 15, 15, 35, 35] 
        headers = ["Nr.", "Track Name", "BPM", "Key", "NRG", "Intro", "Mix-Out"]
        for i, h in enumerate(headers):
            self.cell(self.cols[i], 8, h, 1, 0, 'C', 1)
        self.ln()

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def create_integrated_pdf(playlist, output_path, config_str, playlist_name):
    if not PDF_AVAILABLE: return
    pdf = PDFReport(orientation='L', unit='mm', format='A4')
    pdf.set_report_title(f"PLAYLIST: {playlist_name}")
    pdf.add_page()
    pdf.set_font('Arial', '', 10)
    pdf.set_text_color(0) 
    pdf.set_font('Arial', 'I', 10)
    pdf.cell(0, 8, f"Config: {config_str} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 0, 1, 'L')
    pdf.ln(2)
    pdf.set_font('Arial', '', 10)
    cols = [15, 110, 15, 15, 15, 35, 35]
    fill = False
    for i, t in enumerate(playlist):
        nr = str(i + 1)
        title = aggressive_clean_name(t['filename'])
        if len(title) > 60: title = title[:57] + "..."
        bpm = f"{t['bpm']:.1f}"
        raw_key = t.get('camelot_key') or t.get('key_full') or "-"
        key = translate_key_to_camelot(raw_key)
        nrg_val = t.get('nrg_display', 5)
        nrg = str(nrg_val)
        cue_in, cue_out = calculate_smart_cues(t['bpm'], t['duration'], t.get('first_downbeat', 0), nrg_val)
        intro_beats = "64b" if (cue_in * (t['bpm']/60)) > 40 else "32b"
        cue_in_txt = f"{fmt_time(cue_in)} ({intro_beats})"
        pdf.set_fill_color(240, 240, 240) 
        pdf.cell(cols[0], 7, nr, 1, 0, 'C', fill)
        pdf.cell(cols[1], 7, title, 1, 0, 'L', fill)
        pdf.cell(cols[2], 7, bpm, 1, 0, 'C', fill)
        pdf.cell(cols[3], 7, key, 1, 0, 'C', fill)
        pdf.cell(cols[4], 7, nrg, 1, 0, 'C', fill)
        pdf.cell(cols[5], 7, cue_in_txt, 1, 0, 'C', fill)
        pdf.cell(cols[6], 7, fmt_time(cue_out), 1, 0, 'C', fill)
        pdf.ln()
        fill = not fill
    try:
        pdf.output(output_path, 'F')
        print(f"--> PDF erfolgreich erstellt: {os.path.basename(output_path)}", flush=True)
    except Exception as e:
        print(f"--> PDF Fehler: {e}", flush=True)

# ==========================================
# 3. SYSTEM HELPER
# ==========================================
def auto_mount_usb():
    mounter = SmartUSBMount()
    mounter.mount() 
    
def init_db(db_path):
    conn = sqlite3.connect(db_path)
    table = "songs"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" (
            id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE, filename TEXT NOT NULL, bpm REAL, key_full TEXT, camelot_key TEXT, energy_avg REAL, energy_norm INTEGER, lufs REAL, duration REAL, mix_out_point REAL, rhythm_quality TEXT, first_downbeat REAL, bars_count INTEGER
        )""")
    conn.close()

    conn = sqlite3.connect(db_path)
    table = "Smartlist"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" ( 
            listUuid TEXT NOT NULL, title TEXT, parentPlaylistPath TEXT, nextPlaylistPath TEXT, nextListUuid TEXT, rules TEXT, lastEditTime DATETIME, CONSTRAINT C_NEXT_LIST_UNIQUE_FOR_PARENT UNIQUE(parentPlaylistPath,nextPlaylistPath,nextListUuid), CONSTRAINT C_NAME_UNIQUE_FOR_PARENT UNIQUE(title,parentPlaylistPath), PRIMARY KEY(listUuid)
        )""")
    conn.close()

    conn = sqlite3.connect(db_path)
    table = "PreparelistEntity"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" (
            id INTEGER PRIMARY KEY AUTOINCREMENT, trackId INTEGER, trackNumber INTEGER, FOREIGN KEY(trackId) REFERENCES Track(id) ON DELETE CASCADE
        )""")
    conn.close()

    conn = sqlite3.connect(db_path)
    table = "PlaylistEntity"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" (
            id INTEGER PRIMARY KEY AUTOINCREMENT, listId INTEGER, trackId INTEGER, databaseUuid TEXT, nextEntityId INTEGER, membershipReference INTEGER, FOREIGN KEY(listId) REFERENCES Playlist(id) ON DELETE CASCADE, CONSTRAINT C_NAME_UNIQUE_FOR_LIST UNIQUE(listId,databaseUuid,trackId)
        )""")
    conn.close()

    conn = sqlite3.connect(db_path)
    table = "Playlist"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, parentListId INTEGER, isPersisted BOOLEAN, nextListId INTEGER, lastEditTime DATETIME, isExplicitlyExported BOOLEAN, CONSTRAINT C_NEXT_LIST_ID_UNIQUE_FOR_PARENT UNIQUE(parentListId,nextListId), CONSTRAINT C_NAME_UNIQUE_FOR_PARENT UNIQUE(title,parentListId)
        )""")
    conn.close()

    conn = sqlite3.connect(db_path)
    table = "PerformanceData"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" (
            trackId INTEGER, trackData BLOB, overviewWaveFormData BLOB, beatData BLOB, quickCues BLOB, loops BLOB, thirdPartySourceId INTEGER, activeOnLoadLoops INTEGER, FOREIGN KEY(trackId) REFERENCES Track(id) ON DELETE CASCADE ON UPDATE CASCADE, PRIMARY KEY(trackId)
        )""")
    conn.close()

    conn = sqlite3.connect(db_path)
    table = "Track"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" (
            id INTEGER PRIMARY KEY AUTOINCREMENT, playOrder INTEGER, length INTEGER, bpm INTEGER, year INTEGER, path TEXT, filename TEXT, bitrate INTEGER, bpmAnalyzed REAL, albumArtId INTEGER, fileBytes INTEGER, title TEXT, artist TEXT, album TEXT, genre TEXT, comment TEXT, label TEXT, composer TEXT, remixer TEXT, key INTEGER, rating INTEGER, albumArt TEXT, timeLastPlayed DATETIME, isPlayed BOOLEAN, fileType TEXT, isAnalyzed BOOLEAN, dateCreated DATETIME, dateAdded DATETIME, isAvailable BOOLEAN, isMetadataOfPackedTrackChanged BOOLEAN, isPerfomanceDataOfPackedTrackChanged BOOLEAN, playedIndicator INTEGER, isMetadataImported BOOLEAN, pdbImportKey INTEGER, streamingSource TEXT, uri TEXT, isBeatGridLocked BOOLEAN, originDatabaseUuid TEXT, originTrackId INTEGER, streamingFlags INTEGER, explicitLyrics BOOLEAN, lastEditTime DATETIME, FOREIGN KEY(albumArtId) REFERENCES AlbumArt(id) ON DELETE RESTRICT, CONSTRAINT C_path UNIQUE(path), CONSTRAINT C_originDatabaseUuid_originTrackId UNIQUE(originDatabaseUuid,originTrackId)
        )""")
    conn.close()

    conn = sqlite3.connect(db_path)
    table = "Pack"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" (
            id INTEGER PRIMARY KEY AUTOINCREMENT, packId TEXT, changeLogDatabaseUuid TEXT, changeLogId INTEGER, lastPackTime DATETIME
        )""")
    conn.close()

    conn = sqlite3.connect(db_path)
    table = "AlbumArt"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" (
            id INTEGER PRIMARY KEY AUTOINCREMENT, hash TEXT, albumArt BLOB
        )""")
    conn.close()

    conn = sqlite3.connect(db_path)
    table = "Information"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS """+table+""" (
            id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT, schemaVersionMajor INTEGER, schemaVersionMinor INTEGER, schemaVersionPatch INTEGER, currentPlayedIndiciator INTEGER, lastRekordBoxLibraryImportReadCounter INTEGER
        )""")
    conn.close()

#    new_uuid = str(uuid.uuid4())
#    print(f"\n -> ⚠️ new_uuid: {new_uuid}", flush=True)
#    conn = sqlite3.connect(db_path)
##    conn.execute("INSERT INTO Information (uuid) VALUES ('ed9f2c05-2056-4381-a38e-7c129a3cce08')")
#    conn.execute("INSERT INTO Information (uuid) VALUES (?)", ("'"+new_uuid+"'"))
#    conn.close()

# drop ?
#   conn = sqlite3.connect(db_path)
#   table = "songs"
#   conn.execute("""
#       CREATE TABLE IF NOT EXISTS """+table+""" (
#
#       )""")
#   conn.close()



def perform_scan(music_folder, db_path):
    print("\n[PHASE 1] Smart-Scan...", flush=True)
    init_db(db_path)
    files = [p for ext in ['*.mp3','*.wav','*.flac'] for p in glob.glob(os.path.join(music_folder, '**', ext), recursive=True)]
    if not files: return 0
    conn = sqlite3.connect(db_path)
    existing = set(); count_new = 0
    try:
        for r in conn.execute("SELECT relative_path FROM songs"): existing.add(r[0])
    except: pass

    for i, fpath in enumerate(files):
        rel_path = os.path.relpath(fpath, music_folder)
        if rel_path in existing: continue
        
        # === NEU: RAM-SCHUTZSCHILD ===
        try:
            file_size_mb = os.path.getsize(fpath) / (1024 * 1024)
            if file_size_mb > 40.0:
                print(f" -> ⚠️ Überspringe Monster-Track (RAM-Schutz): {os.path.basename(fpath)} ({file_size_mb:.1f} MB)", flush=True)
                continue
        except Exception:
            pass
        # =============================

        if count_new % 5 == 0: print(f" -> Analysiere: {os.path.basename(fpath)}", flush=True)
        try:
            data = analyze_song(fpath) 
            if data:
                en = data.get('energy_norm', 5)
                e_avg = data.get('energy_avg', 0.5)
                conn.execute("INSERT OR REPLACE INTO songs (relative_path, filename, bpm, key_full, camelot_key, energy_avg, energy_norm, lufs, duration, mix_out_point, rhythm_quality, first_downbeat, bars_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", 
                (rel_path, os.path.basename(fpath), data['bpm'], data['key_full'], data['camelot_key'], e_avg, en, data['lufs'], data['duration'], data['mix_out_point'], data['rhythm_quality'], data['first_downbeat'], data['bars_count']))
                conn.commit(); count_new += 1
        except Exception: pass
    conn.close()
    return len(files)

# ==========================================
# MAIN WORKFLOW
# ==========================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("music_folder") 
    parser.add_argument("--length", type=int, default=20)
    parser.add_argument("--force-analysis", action="store_true")
    parser.add_argument("--bpm-limit", type=float, default=2.0) 
    parser.add_argument("--energy-weight", type=float, default=1.0)
    args = parser.parse_args()

    print(f"\n--- AI-DJ MOTOR V15 (STABLE CORE) ---", flush=True)
    auto_mount_usb()
    MUSIC_FOLDER = args.music_folder 
    
    # 1. SCAN
    raw_files = glob.glob(os.path.join(MUSIC_FOLDER, "**/*.mp3"), recursive=True)
    phys_count = len(raw_files)
    print(f"📂 Ordner Check: {phys_count} MP3s gefunden.", flush=True)

    project_name = os.path.basename(os.path.normpath(MUSIC_FOLDER))
    output_folder_web = f"{project_name}_ergebnisse"
    if not os.path.exists(output_folder_web): os.makedirs(output_folder_web)
    db_path = os.path.join(output_folder_web, "music_library_v3_final.db")

    if args.force_analysis and os.path.exists(db_path): os.remove(db_path)
    if not os.path.exists(db_path): perform_scan(MUSIC_FOLDER, db_path)
    else:
        conn = sqlite3.connect(db_path)
        try: db_count = conn.execute("SELECT count(*) FROM songs").fetchone()[0]
        except: db_count = 0
        conn.close()
        if db_count < phys_count: perform_scan(MUSIC_FOLDER, db_path)

    # 2. GENERATE
    print("\n[PHASE 2] Generiere Playlist...", flush=True)
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    try: all_tracks = [dict(row) for row in conn.execute("SELECT * FROM songs WHERE bpm > 0 ORDER BY bpm ASC").fetchall()]
    except: all_tracks = []
    conn.close()

    if not all_tracks: print("❌ FEHLER: Datenbank leer."); sys.exit(1)
    
    playlist = [all_tracks.pop(0)] 
    while len(playlist) < args.length and all_tracks:
        last = playlist[-1]
        limit_bpm = last['bpm'] + args.bpm_limit
        candidates = []
        candidates_idx = []
        for i, t in enumerate(all_tracks):
            if t['bpm'] >= (last['bpm'] - 1.0) and t['bpm'] <= limit_bpm:
                candidates.append(t); candidates_idx.append(i)

        selected = None; selected_idx = -1
        if candidates:
            best_score = 999
            for i, cand in enumerate(candidates):
                bpm_diff = abs(cand['bpm'] - last['bpm'])
                e_last = last.get('energy_avg', 0.5) or 0.5
                e_cand = cand.get('energy_avg', 0.5) or 0.5
                nrg_diff = abs(e_cand - e_last) * 10 
                score = bpm_diff + (nrg_diff * args.energy_weight)
                if score < best_score: best_score = score; selected = cand; selected_idx = candidates_idx[i]
        
        if not selected: selected = all_tracks[0]; selected_idx = 0
        playlist.append(selected)
        all_tracks.pop(selected_idx)

    playlist = recalibrate_playlist_energy(playlist)
    playlist_name = f"AI-Set-{datetime.now().strftime('%d-%H%M')}"
    print(f"\n✅ GENERATED NAME: {playlist_name}", flush=True)

    # 3. EXPORT
    print(f"\n[PHASE 3] Exportiere Files ({len(playlist)} Tracks)...", flush=True)
    txt_file_web = os.path.join(output_folder_web, f"ki_set_{len(playlist)}.txt")
    pdf_file_web = txt_file_web.replace(".txt", ".pdf")
    
    with open(txt_file_web, 'w', encoding='utf-8') as f:
        f.write(f"PLAYLIST: {playlist_name}\n") 
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Config: R={args.bpm_limit} E={args.energy_weight}\n")
        f.write("-" * 125 + "\n")
        f.write(f"{'Nr':<3} | {'Title':<45} | {'BPM':<6} | {'Key':<4} | {'NRG':<4} | {'Intro':<12} | {'Mix-Out':<8}\n")
        f.write("-" * 125 + "\n")
        for i, t in enumerate(playlist):
            dname = aggressive_clean_name(t['filename'])
            if len(dname) > 43: dname = dname[:40] + "..."
            raw_key = t.get('camelot_key') or t.get('key_full')
            key = translate_key_to_camelot(raw_key)
            nrg = t.get('nrg_display', 5)
            cue_in, cue_out = calculate_smart_cues(t['bpm'], t['duration'], t.get('first_downbeat', 0), nrg)
            intro_beats = "64b" if (cue_in * (t['bpm']/60)) > 40 else "32b"
            cue_in_txt = f"{fmt_time(cue_in)} ({intro_beats})"
            f.write(f"{i+1:<3} | {dname:<45} | {t['bpm']:<6.1f} | {key:<4} | {nrg:<4} | {cue_in_txt:<12} | {fmt_time(cue_out):<8}\n")

    create_integrated_pdf(playlist, pdf_file_web, f"R={args.bpm_limit}, E={args.energy_weight}", playlist_name)
    
    # 4. DEPLOY
    print(f"\n[PHASE 4] Stick Deployment...", flush=True)
    dest_txt = os.path.join(MUSIC_FOLDER, f"{playlist_name}.txt")
    try: shutil.copyfile(txt_file_web, dest_txt)
    except: subprocess.run(["sudo", "cp", txt_file_web, dest_txt], check=False)
        
    # ==========================================
    # 5. DB UPDATE (THE HOLY GRAIL - V15)
    # ==========================================
    denon_db_path = os.path.join(MOUNT_TARGET, DENON_DB_REL_PATH)
    print(f"\n -> ⚠️ db_path: {db_path}\n -> ⚠️ denon_db_path: {denon_db_path}", flush=True)
    shutil.copyfile(db_path, denon_db_path)

    print(f"\n[PHASE 5] Denon DB Update (qnd)...", flush=True)


    new_uuid = str(uuid.uuid4())
    print(f"\n -> ⚠️ new_uuid: {new_uuid}", flush=True)
    #cur.execute("INSERT INTO Information (uuid) VALUES ('ed9f2c05-2056-4381-a38e-7c129a3cce08')")
    #cur.execute("INSERT INTO Information VALUES (1, ?, 3, 0, 1, -6499374409812624455, NULL)", ("'"+new_uuid+"'"))


    #cur = sqlite3.connect(db_path)
    cur = sqlite3.connect(denon_db_path)
    #cur.execute("INSERT INTO Information (uuid) VALUES ('ed9f2c05-2056-4381-a38e-7c129a3cce08')")
    #cur.execute("INSERT INTO Information (uuid) VALUES (?)", ("'"+new_uuid+"'"))
    #cur.close()
# --
# -- ------------------------------------------------------------------------------------------------------
# --
    cur.execute("INSERT INTO Information (id,uuid,schemaVersionMajor,schemaVersionMinor,schemaVersionPatch,currentPlayedIndiciator,lastRekordBoxLibraryImportReadCounter) VALUES (1,'c27b6322-f420-43f8-9a7e-1a9477944393',3,0,1,-6499374409812624455,NULL)")
    cur.execute("INSERT INTO AlbumArt (id,hash,albumArt) VALUES (1,NULL,NULL)")
    cur.execute("INSERT INTO Track (id,playOrder,length,bpm,year ,path,filename,bitrate,bpmAnalyzed,albumArtId,fileBytes,title,artist,album,genre,comment,label,composer,remixer,key,rating,albumArt,timeLastPlayed,isPlayed,fileType,isAnalyzed,dateCreated,dateAdded,isAvailable,isMetadataOfPackedTrackChanged,isPerfomanceDataOfPackedTrackChanged,playedIndicator,isMetadataImported,pdbImportKey,streamingSource,uri,isBeatGridLocked,originDatabaseUuid,originTrackId,streamingFlags,explicitLyrics,lastEditTime) SELECT id,bars_count,printf('%.0f', duration),NULL ,2026,'../denon_tst/'||filename,filename,printf('%.0f', bpm),NULL,1,NULL,filename,filename,'ALBUM',NULL,bars_count,NULL,NULL,NULL,-1,0,NULL,NULL,0,'mp3',0,1772278870,1772278870,1,0,0,NULL,1,0,NULL,NULL,0,'c27b6322-f420-43f8-9a7e-1a9477944393',id,0,0,1772278870 FROM songs order by id asc")
    cur.execute("INSERT INTO PerformanceData (trackId,trackData,overviewWaveFormData,beatData,quickCues,loops,thirdPartySourceId,activeOnLoadLoops) SELECT id,NULL,NULL,NULL,NULL,NULL,NULL,NULL FROM songs order by id asc")
    cur.execute("INSERT INTO Playlist (id,title,parentListId,isPersisted,nextListId,lastEditTime,isExplicitlyExported) VALUES (1,'test',0,1,0,'2026-03-01 13:22:45',1)")
    cur.execute("INSERT INTO PlaylistEntity(listId,trackId,databaseUuid,nextEntityId,membershipReference) SELECT 1,id,'c27b6322-f420-43f8-9a7e-1a9477944393',id - 1,0 FROM Track order by playOrder asc")
    cur.execute("update PlaylistEntity set nextEntityId=id -1; --INSERT INTO PlaylistEntity(id,listId,trackId,databaseUuid,nextEntityId,membershipReference)")

    cur.execute("DROP INDEX IF EXISTS index_PreparelistEntity_trackId")
    cur.execute("CREATE INDEX IF NOT EXISTS index_PreparelistEntity_trackId ON PreparelistEntity ( trackId)")
    cur.execute("DROP INDEX IF EXISTS index_PlaylistEntity_nextEntityId_listId")
    cur.execute("CREATE INDEX IF NOT EXISTS index_PlaylistEntity_nextEntityId_listId ON PlaylistEntity ( nextEntityId, listId)")
    cur.execute("DROP INDEX IF EXISTS index_Track_bpmAnalyzed")
    cur.execute("CREATE INDEX index_Track_bpmAnalyzed ON Track(CAST(bpmAnalyzed + 0.5 AS int))")
    cur.execute("DROP INDEX IF EXISTS index_Track_key")
    #cur.execute("CREATE INDEX IF NOT EXISTS index_Track_key ON Track ( KEYWORDASCOLUMNNAME)")
    cur.execute("DROP INDEX IF EXISTS index_Track_album")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_album ON Track ( album)")
    cur.execute("DROP INDEX IF EXISTS index_Track_artist")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_artist ON Track ( artist)")
    cur.execute("DROP INDEX IF EXISTS index_Track_genre")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_genre ON Track ( genre)")
    cur.execute("DROP INDEX IF EXISTS index_Track_dateAdded")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_dateAdded ON Track ( dateAdded)")
    cur.execute("DROP INDEX IF EXISTS index_Track_year")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_year ON Track ( year)")
    cur.execute("DROP INDEX IF EXISTS index_Track_rating")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_rating ON Track ( rating)")
    cur.execute("DROP INDEX IF EXISTS index_Track_length")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_length ON Track ( length)")
    cur.execute("DROP INDEX IF EXISTS index_Track_title")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_title ON Track ( title)")
    cur.execute("DROP INDEX IF EXISTS index_Track_uri")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_uri ON Track ( uri)")
    cur.execute("DROP INDEX IF EXISTS index_Track_albumArtId")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_albumArtId ON Track ( albumArtId)")
    cur.execute("DROP INDEX IF EXISTS index_Track_filename")
    cur.execute("CREATE INDEX IF NOT EXISTS index_Track_filename ON Track ( filename)")
    cur.execute("DROP INDEX IF EXISTS index_AlbumArt_hash")
    cur.execute("CREATE INDEX IF NOT EXISTS index_AlbumArt_hash ON AlbumArt ( hash)")
    cur.execute("DROP TRIGGER IF EXISTS trigger_before_delete_PlaylistEntity")
    cur.execute("CREATE TRIGGER trigger_before_delete_PlaylistEntity BEFORE DELETE ON PlaylistEntity WHEN OLD.trackId > 0 BEGIN  UPDATE PlaylistEntity SET   nextEntityId = OLD.nextEntityId  WHERE nextEntityId = OLD.id  AND listId = OLD.listId; END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_insert_isPersist")
    cur.execute("CREATE TRIGGER trigger_after_insert_isPersist AFTER INSERT ON Playlist  WHEN new.isPersisted = 1 BEGIN  UPDATE Playlist SET   isPersisted = 1  WHERE id IN (SELECT parentListId FROM PlaylistAllParent WHERE id=new.id); END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_update_isPersistChild")
    cur.execute("CREATE TRIGGER trigger_after_update_isPersistChild AFTER UPDATE ON Playlist  WHEN old.isPersisted = 1  AND new.isPersisted = 0 BEGIN  UPDATE Playlist SET   isPersisted = 0  WHERE id IN (SELECT childListId FROM PlaylistAllChildren WHERE id=new.id); END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_update_isPersistParent")
    cur.execute("CREATE TRIGGER trigger_after_update_isPersistParent AFTER UPDATE ON Playlist  WHEN (old.isPersisted = 0  AND new.isPersisted = 1)  OR (old.parentListId != new.parentListId  AND new.isPersisted = 1) BEGIN  UPDATE Playlist SET   isPersisted = 1  WHERE id IN (SELECT parentListId FROM PlaylistAllParent WHERE id=new.id); END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_delete_List")
    cur.execute("CREATE TRIGGER trigger_after_delete_List AFTER DELETE ON Playlist FOR EACH ROW BEGIN  UPDATE Playlist SET   nextListId = OLD.nextListId  WHERE nextListId = OLD.id;  DELETE FROM Playlist  WHERE parentListId = OLD.id; END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_insert_List")
    cur.execute("CREATE TRIGGER trigger_after_insert_List AFTER INSERT ON Playlist FOR EACH ROW BEGIN  UPDATE Playlist SET   nextListId = NEW.id  WHERE nextListId = -(1 + NEW.nextListId)  AND parentListId = NEW.parentListId; END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_before_insert_List")
    cur.execute("CREATE TRIGGER trigger_before_insert_List BEFORE INSERT ON Playlist FOR EACH ROW BEGIN  UPDATE Playlist SET   nextListId = -(1 + nextListId)  WHERE nextListId = NEW.nextListId  AND parentListId = NEW.parentListId; END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_PerformanceData_after_update_Track_timestamp")
    cur.execute("CREATE TRIGGER trigger_PerformanceData_after_update_Track_timestamp  AFTER UPDATE OF trackData, isAnalyzed, overviewWaveFormData, beatData, quickCues, loops, activeOnLoadLoops  ON PerformanceData  FOR EACH ROW BEGIN  UPDATE Track  SET lastEditTime = strftime('%s')  WHERE id = NEW.trackId; END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_insert_Track_insert_performance_data")
    cur.execute("CREATE TRIGGER trigger_after_insert_Track_insert_performance_data AFTER INSERT ON Track BEGIN  INSERT INTO PerformanceData(trackId) VALUES(NEW.id); END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_update_only_Track_timestamp")
    cur.execute("CREATE TRIGGER trigger_after_update_only_Track_timestamp  AFTER UPDATE OF length, bpm, year, filename, bitrate, bpmAnalyzed, albumArtId,  title, artist, album, genre, comment, label, composer, remixer, key, rating, albumArt,  fileType, isAnalyzed, isBeatgridLocked, explicitLyrics  ON Track  FOR EACH ROW BEGIN  UPDATE Track SET lastEditTime = strftime('%s') WHERE ROWID=NEW.ROWID; END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_update_Track_fix_origin")
    cur.execute("CREATE TRIGGER trigger_after_update_Track_fix_origin AFTER UPDATE ON Track  WHEN IFNULL(NEW.originTrackId, 0) = 0  OR IFNULL(NEW.originDatabaseUuid, '') = '' BEGIN  UPDATE Track SET   originTrackId = NEW.id,   originDatabaseUuid = (SELECT uuid FROM Information)  WHERE track.id = NEW.id; END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_insert_Track_fix_origin")
    cur.execute("CREATE TRIGGER trigger_after_insert_Track_fix_origin AFTER INSERT ON Track  WHEN IFNULL(NEW.originTrackId, 0) = 0  OR IFNULL(NEW.originDatabaseUuid, '') = '' BEGIN  UPDATE Track SET   originTrackId = NEW.id,   originDatabaseUuid = (SELECT uuid FROM Information)  WHERE track.id = NEW.id; END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_update_Track_check_Id")
    cur.execute("CREATE TRIGGER trigger_after_update_Track_check_Id BEFORE UPDATE ON Track  WHEN NEW.id <> OLD.id BEGIN  SELECT RAISE(ABORT, 'Changing track id''s are not allowed'); END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_insert_Track_check_id")
    cur.execute("CREATE TRIGGER trigger_after_insert_Track_check_id AFTER INSERT ON Track  WHEN NEW.id <= (SELECT seq FROM sqlite_sequence WHERE name = 'Track') BEGIN  SELECT RAISE(ABORT, 'Recycling deleted track id''s are not allowed'); END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_insert_Pack_changeLogId")
    cur.execute("CREATE TRIGGER trigger_after_insert_Pack_changeLogId AFTER INSERT ON Pack FOR EACH ROW WHEN NEW.changeLogId = 0 BEGIN  UPDATE Pack SET changeLogId = 1 WHERE ROWID = NEW.ROWID; END")
    cur.execute("DROP TRIGGER IF EXISTS trigger_after_insert_Pack_timestamp")
    cur.execute("CREATE TRIGGER trigger_after_insert_Pack_timestamp AFTER INSERT ON Pack FOR EACH ROW WHEN NEW.lastPackTime IS NULL BEGIN  UPDATE Pack SET lastPackTime = strftime('%s') WHERE ROWID = NEW.ROWID; END")
    cur.execute("DROP VIEW IF EXISTS PlaylistPath")
#    cur.execute("CREATE VIEW PlaylistPath AS WITH RECURSIVE Heirarchy AS (  SELECT id AS child, parentListId AS parent, title AS name, 1 AS depth FROM Playlist  UNION ALL  SELECT child, parentListId AS parent, title AS name, h.depth + 1 AS depth FROM Playlist c  JOIN Heirarchy h ON h.parent = c.id  ORDER BY depth DESC ), OrderedList AS (  SELECT id , nextListId, 1 AS position  FROM Playlist  WHERE nextListId = 0  UNION ALL  SELECT c.id , c.nextListId , l.position + 1  FROM Playlist c  INNER JOIN OrderedList l  ON c.nextListId = l.id ), NameConcat AS (  SELECT   child AS id,   GROUP_CONCAT(name ,';') || ';' AS path  FROM  (   SELECT child, name   FROM Heirarchy   ORDER BY depth DESC  )  GROUP BY child ) SELECT  id,  path,  ROW_NUMBER() OVER  (   ORDER BY   (SELECT COUNT(*) FROM (SELECT * FROM Heirarchy WHERE child = id) ) DESC,   (SELECT position FROM OrderedList ol WHERE ol.id = c.id) ASC  ) AS position FROM Playlist c LEFT JOIN NameConcat g USING (id);DROP VIEW IF EXISTS PlaylistAllChildren;CREATE VIEW PlaylistAllChildren AS WITH FindAllChild AS ( SELECT id, id as childListId FROM Playlist UNION ALL SELECT recursiveCTE.id, Plist.id FROM Playlist Plist INNER JOIN FindAllChild recursiveCTE ON recursiveCTE.childListId = Plist.parentListId )")
    #SELECT * FROM FindAllChild WHERE id <> childListId")
    cur.execute("DROP VIEW IF EXISTS PlaylistAllParent")
    cur.execute("CREATE VIEW PlaylistAllParent AS WITH FindAllParent AS (  SELECT id, parentListId FROM Playlist  UNION ALL  SELECT recursiveCTE.id, Plist.parentListId FROM Playlist Plist  INNER JOIN FindAllParent recursiveCTE  ON recursiveCTE.parentListId = Plist.id ) SELECT * FROM FindAllParent")
    cur.execute("DROP VIEW IF EXISTS ChangeLog")
    cur.execute("CREATE VIEW ChangeLog (id, trackId) AS SELECT 0, 0 WHERE FALSE")

# --
# --
# -- ------------------------------------------------------------------------------------------------------
    cur.commit()
    cur.close()


    denon_db_path = "do_nothing_from_here"
    if os.path.exists(denon_db_path):
        print(f"\n[PHASE 5] Denon DB Update (STRICT BOUNCER)...", flush=True)
        if not os.access(denon_db_path, os.W_OK):
             subprocess.run(["sudo", "chmod", "666", denon_db_path], check=False)

        try:
            dconn = sqlite3.connect(denon_db_path)
            cur = dconn.cursor()
            
            # --- 1. MASTER UUID ABRUFEN ---


            new_uuid = str(uuid.uuid4())
            print(f"\n -> ⚠️ new_uuid: {new_uuid}", flush=True)
            cur.execute("INSERT INTO Information (uuid) VALUES ('ed9f2c05-2056-4381-a38e-7c129a3cce08')")
            #cur.execute("INSERT INTO Information VALUES (1, ?, 3, 0, 1, -6499374409812624455, NULL)", ("'"+new_uuid+"'"))


            cur.execute("SELECT uuid FROM Information LIMIT 1;")
            res = cur.fetchone()
            if not res:
                print("❌ KRITISCHER FEHLER: Keine UUID in der Datenbank gefunden!", flush=True)
                raise ValueError("Missing UUID")
            
            target_uuid = res[0]
            print(f" -> Master-UUID erfolgreich geladen: {target_uuid}", flush=True)
            
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # --- 2. NEUE PLAYLIST ERSTELLEN ---
            cur.execute("""
                INSERT INTO Playlist (title, parentListId, isPersisted, isExplicitlyExported, nextListId, lastEditTime) 
                VALUES (?, 0, 1, 1, NULL, ?)
            """, (playlist_name, now_str))
            new_pid = cur.lastrowid
            print(f" -> Neue Playlist angelegt: ID {new_pid} ({playlist_name})", flush=True)

            # --- 3. PLAYLIST KETTE SCHLIESSEN (THE ZIPPER) ---
            cur.execute("SELECT id FROM Playlist WHERE parentListId = 0 ORDER BY id ASC")
            all_root = [r[0] for r in cur.fetchall()]
            
            for pid in all_root:
                cur.execute("UPDATE Playlist SET nextListId = NULL WHERE id = ?", (pid,))
                
            for i in range(len(all_root)):
                current_id = all_root[i]
                next_target = all_root[i+1] if i < len(all_root) - 1 else 0
                cur.execute("UPDATE Playlist SET nextListId = ? WHERE id = ?", (next_target, current_id))
                
            print(" -> Playlist-Kette finalisiert.", flush=True)

            # --- 4. TRACKS SUCHEN, VERIFIZIEREN & PFADE HEILEN (AUTO-HEALER) ---
            valid_track_ids = []
            for t in playlist:
                filename = t['filename']
                name_no_ext = filename.rsplit('.', 1)[0]
                
                cur.execute("SELECT id FROM Track WHERE filename = ?", (filename,))
                res = cur.fetchone()
                
                if not res:
                    cur.execute("SELECT id FROM Track WHERE filename = ?", (name_no_ext,))
                    res = cur.fetchone()
                    
                if not res:
                    cur.execute("SELECT id FROM Track WHERE path LIKE ?", (f"%{filename}%",))
                    res = cur.fetchone()
                
                if res:
                    track_id = res[0]
                    valid_track_ids.append(track_id)
                    
                    # === THE AUTO-HEALER: Pfad in der Matrix erzwingen ===
                    # 1. Absoluter Pfad der Datei auf dem Raspi (z.B. /mnt/denon/DJ-Set/Track.mp3)
                    abs_path = os.path.join(MUSIC_FOLDER, t['relative_path'])
                    # 2. Relativer Pfad vom USB-Root aus (z.B. DJ-Set/Track.mp3)
                    rel_to_root = os.path.relpath(abs_path, MOUNT_TARGET)
                    # 3. Denon-Format generieren (Linux-Slashes + '../' davor)
                    denon_path = "../" + rel_to_root.replace("\\", "/")
                    
                    # Matrix mit der Realität überschreiben!
                    cur.execute("UPDATE OR IGNORE Track SET path = ? WHERE id = ?", (denon_path, track_id))
                    #cur.execute("UPDATE Track SET path = ? WHERE id = ?", (denon_path, track_id))
                    
                else:
                    print(f" -> ⚠️ Übersprungen (Nicht in Denon DB gefunden): {filename}", flush=True)            

            # --- 5. TRACKS ALS PERLENKETTE EINFÜGEN ---
            cur.execute("PRAGMA table_info(PlaylistEntity)")
            cols = [r[1] for r in cur.fetchall()]
            is_legacy = 'trackOrder' not in cols
            list_col = 'playlistId' if 'playlistId' in cols else 'listId'
            
            linked = 0
            if not is_legacy:
                # Modern Engine OS (nutzt trackOrder statt nextEntityId)
                for i, tid in enumerate(valid_track_ids):
                    cur.execute(f"INSERT INTO PlaylistEntity ({list_col}, trackId, trackOrder, databaseUuid) VALUES (?, ?, ?, ?)", 
                                (new_pid, tid, i + 1, target_uuid))
                    linked += 1
            else:
                # Legacy Engine OS - Die magische Rückwärts-Schleife!
                next_entity_id = 0
                for tid in reversed(valid_track_ids):
                    cur.execute(f"""
                        INSERT INTO PlaylistEntity ({list_col}, trackId, databaseUuid, nextEntityId) 
                        VALUES (?, ?, ?, ?)
                    """, (new_pid, tid, target_uuid, next_entity_id))
                    
                    # Die ID des gerade eingefügten Tracks für den nächsten Durchlauf merken
                    next_entity_id = cur.lastrowid 
                    linked += 1

            dconn.commit()

            print(" -> Checkpoint & Sync...", flush=True)
            dconn.execute("PRAGMA wal_checkpoint(FULL)")
            dconn.close()
            subprocess.run("sync", shell=True)
            time.sleep(2.0)
            
            print(f"✅ VERIFIKATION: {linked} Tracks erfolgreich als Kette geschmiedet!", flush=True)
            
        except Exception as e:
            print(f"❌ DB Fehler: {e}", flush=True)

    print(f"\n✅ FERTIG! Datei: {txt_file_web}", flush=True)

if __name__ == "__main__":
    main()
