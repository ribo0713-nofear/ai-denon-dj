AI-DJ Studio V5 (Motor V15 Stable Core)
Willkommen beim AI-DJ Studio! Dieses System ist eine autonome KI-Pipeline für Denon Engine OS. Es analysiert Musik auf einem USB-Stick (BPM, Camelot-Key, Energie-Level) und generiert in Sekundenbruchteilen dynamische, harmonisch perfekte Playlisten.
Das absolute Highlight: Die generierten Playlisten werden über ein Reverse-Engineering-Verfahren (BLOB-Injection) nativ und direkt in die SQLite-Datenbank des Denon-Controllers geschrieben. Kein Umweg über den PC für die Playlist-Erstellung mehr!

🏗️ System-Architektur & Module
Dieses Projekt folgt einer sauberen, modularen Architektur. Es besteht aus dem Frontend (UI), dem Core-Orchestrator im Hauptverzeichnis und spezialisierten "Worker"-Modulen im modules/ Ordner:

Hauptverzeichnis (Core):
studio_web_v5.py (Das Frontend): Die grafische Kommandozentrale (Streamlit). Hier wählt der User den Ordner aus, regelt die Parameter (Energy, Randomness) und feuert den Motor an.
main_workflow_v10.py (Der Core-Orchestrator): Das Bindeglied. Es steuert die 5 Phasen des Systems: Smart-Scan -> Playlist-Generierung -> PDF/TXT Export -> Stick Deployment -> Denon DB Injection (BLOB).
Der modules/ Ordner (Die Engine):
smart_usb_mount.py: Der Hardware-Wächter. Kümmert sich um das sichere Einbinden (mount) und Auswerfen (umount) des USB-Sticks auf Linux-Ebene, um eine Korruption der m.db Datenbank zu verhindern.
analysis_engine_v3.py: Der Audio-Scanner. Nutzt librosa, um BPM, Key (Tonart) und die dynamischen Energie-Level der MP3-Dateien zu berechnen. Inklusive RAM-Schutzschild, der bei Monster-Tracks (>40 MB) automatisch greift, um Abstürze zu verhindern.
playlist_manager.py: Das musikalische Gehirn. Dieses Skript übernimmt die Auswahl und Anordnung der Tracks basierend auf dem Camelot-Wheel (Harmonie) und dem berechneten Spannungsbogen (Energy-Level).

🧠 Das Konzept: Architekt vs. Maurer
Um dieses System erfolgreich zu nutzen, musst du die Aufgabenteilung zwischen der offiziellen Engine DJ Software (PC/Mac) und unserem AI-DJ (Raspberry Pi/Linux) verstehen.
Der Maurer (Engine DJ am PC): Gießt das Fundament. Die PC-Software ist zwingend notwendig, um neue MP3s zu scannen und die Wellenformen, Beatgrids und internen Track-IDs in die Denon-Datenbank (m.db) zu schreiben. Ohne dieses Fundament weiß der Hardware-Player nicht, wie er die Musik grafisch darstellen soll.
Der Architekt (AI-DJ am Raspi): Baut das Haus. Sobald das Fundament steht, übernimmt die KI. Sie analysiert die harmonische Kompatibilität, berechnet den Spannungsbogen und injiziert die fertigen Setlisten als native Binärdaten (BLOBs) direkt auf den Stick.

🚀 Der "Golden Path" Workflow (Schritt-für-Schritt)
Wenn du neue Musik hast, halte dich strikt an diese Reihenfolge:
Das Fundament (PC): Zieh neue MP3s am PC in Engine DJ und exportiere/synchronisiere sie auf den USB-Stick.
Die KI-Magie (Raspberry Pi): Steck den Stick in den Raspi. Öffne das Web-UI (studio_web_v5.py). Wähle den Ordner, setze die Parameter und klicke auf "🚀 START AI-ENGINE V5". (Dauer: ca. 2-5 Sekunden bei bereits gescannten Ordnern).
Showtime (Denon Player): Wirf den Stick über das UI sicher aus (EJECT). Steck ihn in dein Denon-Equipment. Lade die brandneue AI-Set Playlist und spiele dein Set!

🛠️ Under the Hood: Core-Features (V15)
Native BLOB-Injection: Das Skript generiert die proprietären, binären blob2 Datenstrukturen von Denon selbst und umgeht die Restriktionen der Hardware.
Der Auto-Healer: Phase 5 vergleicht die echten Linux-Pfade der MP3s mit den alten Einträgen in der Denon-Datenbank und repariert kaputte/verschobene Pfade im Vorbeigehen.
Der Türsteher (Strict Bouncer): Das System prüft, ob Tracks in der Denon-DB offiziell registriert sind. Unbekannte Tracks werden übersprungen, um leere Zeilen auf dem Display zu verhindern.

💻 Installation & Setup
1. System-Voraussetzungen
Raspberry Pi 4 (ab 4GB RAM) oder Pi 5 / Standard Linux, macOS, Windows.

Python 3.8+

2. OS-Abhängigkeiten installieren
Für die Audio-Analyse via librosa benötigt das Betriebssystem diese Codecs:

Bash
sudo apt-get update
sudo apt-get install -y ffmpeg libsndfile1
3. Python-Umgebung einrichten
Nutze die beiliegende requirements.txt:

Bash
python3 -m venv ai_dj_env
source ai_dj_env/bin/activate
pip install -r requirements.txt
4. Starten
Bash
streamlit run studio_web_v5.py
Damit hast du das perfekte Dokument. Einfach im Terminal nano README.md eintippen, das hier reinkopieren, speichern und dann den Git-Push feuern! Sag Bescheid, wenn das Ding online ist! 🚀
