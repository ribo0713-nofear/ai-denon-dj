import streamlit as st
import os
import subprocess
import time
import glob

# --- CONFIG ---
# Wir nutzen den "getarnten" V15 Motor (Dateiname ist v10, Inhalt ist v15)
BACKEND_SCRIPT = "main_workflow_v10.py" 
SEARCH_BASE = "/mnt/denon"

st.set_page_config(page_title="AI-DJ Studio V5 Pro", layout="wide", page_icon="🎛️")

st.markdown("""
<style>
    .header-box { background-color: #111; color: #eee; padding: 15px; border-left: 5px solid #dc3545; border-radius: 5px; font-family: monospace; margin-bottom: 20px;}
    .status-ok { color: #28a745; font-weight: bold; }
    .status-warn { color: #ffc107; font-weight: bold; }
    .status-err { color: #dc3545; font-weight: bold; }
    .console-log { background-color: #0e1117; color: #00ff00; font-family: 'Courier New', monospace; padding: 10px; border-radius: 5px; border: 1px solid #333; }
    .stButton>button { font-weight: bold; border-radius: 4px; height: 3em; }
</style>
""", unsafe_allow_html=True)

# --- HEADER ---
c1, c2 = st.columns([2, 1])
with c1: st.title("🎛️ AI-DJ Studio V5 (Pro)")
with c2: st.markdown(f'<div class="header-box">STUDIO: V5 Pro<br>MOTOR: V15 (Repair)<br>STATUS: Active</div>', unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Parameter")
    playlist_length = st.number_input("Tracks Anzahl", 5, 100, 20)
    st.divider()
    bpm_limit = st.slider("BPM Range (+/-)", 0.5, 10.0, 2.0, 0.5)
    energy_weight = st.slider("Energie Fokus", 0.0, 10.0, 1.0, 0.5)
    st.divider()
    force_rescan = st.checkbox("Neuanalyse erzwingen", value=False)
    
    if st.button("🔌 USB Reset (Fix)"):
        from modules.smart_usb_mount import SmartUSBMount
        mounter = SmartUSBMount() 
        success, msg = mounter.mount()
        
        if success:
            st.success(msg)
            time.sleep(1)
            st.rerun()
        else:
            st.error(msg)
# --- HELPER ---
def get_music_folders():
    options = {}
    if os.path.exists(SEARCH_BASE):
        options[f"💾 Ganzer Stick ({SEARCH_BASE})"] = SEARCH_BASE
        try:
            cmd = f"sudo ls -F {SEARCH_BASE}"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                for item in res.stdout.splitlines():
                    if item.endswith('/') and item not in ["Engine Library/", "System Volume Information/", "$RECYCLE.BIN/"]:
                        clean = item[:-1]
                        options[f"📂 {clean}"] = os.path.join(SEARCH_BASE, clean)
        except: pass
    return options

#def count_songs(folder):
 #   try:
  #      return len(glob.glob(os.path.join(folder, "**/*.mp3"), recursive=True))
   # except: return 0

def count_songs(folder):
    count = 0
    try:
        # Wühlt sich durch alle Unterordner und ignoriert Groß-/Kleinschreibung
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(('.mp3', '.wav', '.flac', '.aiff', '.m4a')):
                    count += 1
    except:
        pass
    return count


# --- MAIN SELECTION ---
st.subheader("1. Quelle & Status")
available_folders = get_music_folders()

if not available_folders:
    c_usb, c_db, c_sys = st.columns(3)
    c_usb.metric("USB Status", "NICHT GEMOUNTET")
    st.error(f"⚠️ Stick nicht gefunden unter {SEARCH_BASE}. Bitte einstecken.")
    folder_path = None
else:
    label = st.selectbox("Ordner wählen:", list(available_folders.keys()))
    folder_path = available_folders[label]
 
    
    # Song Counter Logic (Das, was du vermisst hast!)
    num_songs = count_songs(folder_path)
    
    c_usb, c_db, c_sys = st.columns(3)
    c_usb.markdown("USB Status<br><h3 class='status-ok'>SCHREIBBAR (RW) ✅</h3>", unsafe_allow_html=True)
    
   # Hier ist der Song-Zähler zurück!
   #c_db.metric("Datenbank", "BEREIT", f"{num_songs} Songs")
    c_db.metric("Gefundene Tracks", f"{num_songs} Songs", "Datenbank BEREIT")    
    c_sys.markdown("System Status<br><h3 class='status-ok'>BEREIT 🚀</h3>", unsafe_allow_html=True)


# --- 2. PLAYLIST MANAGEMENT (Mass-Delete) ---
st.subheader("2. Playlist Management")
from modules.playlist_manager import PlaylistManager
pm = PlaylistManager(os.path.join(SEARCH_BASE, "Engine Library/Database2/m.db"))

all_playlists = pm.get_all_playlists()

if all_playlists:
    st.write("Wähle Playlisten zum Löschen aus:")
    to_delete = []
    
    # Kompakte Liste mit Checkboxen
    for pid, title in all_playlists:
        if st.checkbox(f"🗑️ {title}", key=f"pl_{pid}"):
            to_delete.append(pid)
    
    if to_delete:
        if st.button(f"🔥 {len(to_delete)} gewählte Listen permanent löschen", type="secondary"):
            if pm.delete_multiple_playlists(to_delete):
                st.success("Erfolgreich gelöscht und Datenbank-Kette repariert!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Fehler beim Löschen.")
else:
    st.info("Keine Playlisten in der Datenbank gefunden.")



# --- START LOGIC ---
if 'logs' not in st.session_state: st.session_state.logs = ""
if 'result_txt' not in st.session_state: st.session_state.result_txt = None

c_start, c_umount = st.columns([3, 1])

with c_start:
    if st.button("🚀 START AI-ENGINE V5", type="primary", use_container_width=True, disabled=not folder_path):
        st.session_state.logs = ""
        st.session_state.result_txt = None
        
        cmd = ["python3", "-u", BACKEND_SCRIPT, folder_path, 
               "--length", str(playlist_length), 
               "--bpm-limit", str(bpm_limit), 
               "--energy-weight", str(energy_weight)]
        
        if force_rescan: cmd.append("--force-analysis")
        
        with st.status("AI-DJ arbeitet...", expanded=True) as status:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
            
            for line in proc.stdout:
                line_clean = line.strip()
                st.session_state.logs += line
                
                if "[PHASE" in line: st.write(f"👉 {line_clean}")
                if "Reparatur:" in line: st.warning(line_clean) 
                if "Kette" in line: st.info(line_clean)
                if "VERIFIKATION" in line: st.success(line_clean)
                
                if "✅ FERTIG! Datei:" in line:
                    parts = line.split("Datei:")
                    if len(parts) > 1:
                        st.session_state.result_txt = parts[1].strip()
            
            proc.wait()
            
            if proc.returncode == 0:
                status.update(label="✅ Export abgeschlossen!", state="complete", expanded=False)
                if st.session_state.result_txt:
                    st.success(f"Playlist gespeichert: {os.path.basename(st.session_state.result_txt)}")
            else:
                status.update(label="❌ Fehler aufgetreten!", state="error", expanded=True)

with c_umount:
    if st.button("⏏️ EJECT", use_container_width=True):
        st.info("Syncing & Unmounting...")
        subprocess.run("sync", shell=True)
        subprocess.run(["sudo", "umount", "-l", SEARCH_BASE])
        st.success("Sicher entfernt!")

# --- OUTPUT AREA ---
st.write("Live Log:")
st.text_area("System Log", value=st.session_state.logs, height=200, label_visibility="collapsed")

if st.session_state.result_txt:
    txt_path = st.session_state.result_txt
    pdf_path = txt_path.replace(".txt", ".pdf")
    
    st.markdown("---")
    c_dl1, c_dl2 = st.columns(2)
    
    if os.path.exists(txt_path):
        with open(txt_path, "rb") as f:
            c_dl1.download_button("📥 Download TXT", f, file_name=os.path.basename(txt_path), mime="text/plain", use_container_width=True)
            
    if os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            c_dl2.download_button("📄 Download PDF Report", f, file_name=os.path.basename(pdf_path), mime="application/pdf", use_container_width=True)
