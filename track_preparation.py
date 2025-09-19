# Track_Preparation_Pipeline.py (Version 1.3 - Korrigierter NameError)

import os
import subprocess
import argparse
import re
from pathlib import Path
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from mutagen import File

# --- KONFIGURATION ---
TARGET_LUFS = -14.0
TARGET_FORMAT = 'mp3'
TARGET_BITRATE = '320k'
GARBAGE_KEYWORDS = [
    'official music video', 'official video', 'music video', 'official audio',
    'hd', '4k', 'lyrics', 'lyric video', 'extended', 'original mix',
    'original', 'feat', 'ft', 'audio', 'visualiser'
]

# ==============================================================================
#  1. Hilfsfunktionen
# ==============================================================================

def clean_filename_for_parsing(filename):
    """Bereinigt einen Dateinamen von gängigem Müll. V1.1 entfernt jetzt auch Hochkommas."""
    name, extension = os.path.splitext(filename)
    name = name.replace("\\'", "")
    name = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}', '', name)
    name = re.sub(r'[\s_-]+[a-zA-Z0-9_-]{11}[\s_]*$', '', name)
    for keyword in GARBAGE_KEYWORDS:
        name = re.sub(r'\b' + re.escape(keyword) + r'\b', '', name, flags=re.IGNORECASE)
    
    name = re.sub(r"[^a-zA-Z0-9\s-]", '', name) 
    
    name = name.replace('_', ' ').replace('-', ' - ')
    cleaned_name = " ".join(name.split()).strip()
    return f"{cleaned_name}{extension}"

def parse_artist_title(cleaned_filename):
    """
    Extrahiert Künstler/Titel. V1.1 gibt None für den Künstler zurück, wenn er nicht erkannt wird.
    """
    name, _ = os.path.splitext(cleaned_filename)
    if ' - ' in name:
        parts = name.split(' - ', 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        return artist, title
    else:
        return None, name

# ==============================================================================
#  2. Die Haupt-Verarbeitungsfunktion
# ==============================================================================

def process_track(input_file, output_folder):
    """
    Verarbeitungspipeline für einen Track. V1.1 behandelt fehlende Künstler sauberer.
    """
    try:
        cleaned_name_ext = clean_filename_for_parsing(input_file.name)
        artist, title = parse_artist_title(cleaned_name_ext)

        if artist:
            final_filename = f"{artist} - {title}.{TARGET_FORMAT}"
        else:
            final_filename = f"{title}.{TARGET_FORMAT}"
            
        output_file = output_folder / final_filename

        print(f"  -> Verarbeite: {input_file.name}")
        if artist:
            print(f"     Erkannt: Artist='{artist}', Title='{title}'")
        else:
            print(f"     Erkannt: Title='{title}' (Kein Künstler gefunden)")
        print(f"     Zieldatei: {final_filename}")

        command = [
            'ffmpeg', '-y', '-i', str(input_file),
            '-af', f'loudnorm=I={TARGET_LUFS}:LRA=7:TP=-2.0',
            '-c:a', 'libmp3lame', '-b:a', TARGET_BITRATE,
            '-map_metadata', '0',
            str(output_file)
        ]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        audio = EasyID3(str(output_file))
        if artist:
            audio['artist'] = artist
        audio['title'] = title
        audio.save()
        
        print(f"     ==> Erfolgreich verarbeitet und getaggt.")
        return True

    except Exception as e:
        print(f"  !! FEHLER bei der Verarbeitung von {input_file.name}: {e}")
        return False

# ==============================================================================
#  3. Der Main-Workflow
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Bereitet einen Ordner mit Audiodateien für den DJ-Einsatz vor.")
    parser.add_argument("input_folder", help="Der Quellordner mit den originalen Musikdateien.")
    parser.add_argument("output_folder", help="Der Zielordner für die bearbeiteten, DJ-fertigen Tracks.")
    args = parser.parse_args()
    
    input_path = Path(args.input_folder)
    output_path = Path(args.output_folder)

    if not input_path.is_dir():
        print(f"FEHLER: Der Quellordner '{input_path}' existiert nicht.")
        return
    if not output_path.exists():
        print(f"Zielordner '{output_path}' wird erstellt.")
        output_path.mkdir(parents=True)
        
    print("\n" + "="*50)
    print(f"--- STARTE TRACK PREPARATION PIPELINE (v1.3) ---")
    print(f"Quelle: {input_path}")
    print(f"Ziel:   {output_path}")
    print("="*50 + "\n")
    
    # --- HIER IST DIE KORREKTUR des Tippfehlers ---
    music_files = list(input_path.glob('**/*.mp3')) + \
                  list(input_path.glob('**/*.wav')) + \
                  list(input_path.glob('**/*.flac')) + \
                  list(input_path.glob('**/*.aiff'))
                  
    total_files = len(music_files)
    for i, file in enumerate(music_files):
        print(f"({i+1}/{total_files}) Starte Verarbeitung für '{file.name}'")
        process_track(file, output_path)
        
    print("\n" + "="*50)
    print("--- PIPELINE ABGESCHLOSSEN ---")
    print(f"Die bearbeiteten Tracks befinden sich in: {output_path}")
    print("="*50)

if __name__ == "__main__":
    main()
