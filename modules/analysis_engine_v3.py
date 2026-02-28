import librosa
import numpy as np
import aubio
import pyloudnorm as pyln
import os

def analyze_song(file_path):
    try:
        y, sr = librosa.load(file_path, sr=44100, mono=True)
        if np.mean(np.abs(y)) < 0.0001: return None

        duration = librosa.get_duration(y=y, sr=sr)
        meter = pyln.Meter(sr)
        loudness = meter.integrated_loudness(y)
        rms = librosa.feature.rms(y=y)[0]

        # --- CUE1 / NOISE GATE ---
        # Wir suchen den ersten Moment, der lauter als -60dB ist (sensibler)
        non_silent_intervals = librosa.effects.split(y, top_db=60)
        start_offset_sec = 0.0
        if len(non_silent_intervals) > 0:
            start_offset_sec = non_silent_intervals[0][0] / sr

        # --- AUBIO BEATS ---
        win_s = 512; hop_s = 256
        tempo_o = aubio.tempo("default", win_s, hop_s, sr)
        aubio_beats = []
        total_frames = 0
        while True:
            samples = y[total_frames : total_frames + hop_s]
            if len(samples) < hop_s: break
            if tempo_o(samples):
                beat_time = tempo_o.get_last_s()
                if beat_time >= start_offset_sec: aubio_beats.append(beat_time)
            total_frames += hop_s

        # BPM
        bpm = 0.0
        if len(aubio_beats) > 1:
            intervals = np.diff(aubio_beats)
            bpm = np.median(60.0 / intervals)
        else:
            t_res, _ = librosa.beat.beat_track(y=y, sr=sr)
            bpm = t_res if not hasattr(t_res, "__len__") else t_res[0]

        # --- SYNC CHECK (Gefixed) ---
        rhythm_quality = "Unknown"
        if len(aubio_beats) > 10:
            intervals = np.diff(aubio_beats)
            # Wir filtern extreme Ausreißer raus (Anfang/Ende)
            clean_intervals = intervals[abs(intervals - np.mean(intervals)) < 0.1]
            if len(clean_intervals) > 5:
                std_dev = np.std(clean_intervals)
                # Neuer Grenzwert: 0.02s (20ms Jitter ist okay für Sync)
                if std_dev < 0.02: 
                    rhythm_quality = "Quantized"
                else: 
                    rhythm_quality = "Dynamic"

        # Bars (Gerundet)
        seconds_per_beat = 60.0 / bpm if bpm > 0 else 1
        bars_count = int(round((duration / seconds_per_beat) / 4.0))

        # Mix-Out
        _, librosa_beats = librosa.beat.beat_track(y=y, sr=sr, units='time')
        mix_out_point = duration - 15.0 
        if librosa_beats.size > 0:
            total_beats = len(librosa_beats)
            if total_beats > 300:
                idx = -96 
                if total_beats > abs(idx): mix_out_point = librosa_beats[idx]
            else:
                idx = -32
                if total_beats > abs(idx): mix_out_point = librosa_beats[idx]

        # Key
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        chroma_avg = np.mean(chroma, axis=1)
        notes = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        maj_p = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
        min_p = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
        best_corr = -1; best_key = None
        for i in range(12):
            corr = np.corrcoef(chroma_avg, np.roll(maj_p, i))[0, 1]
            if corr > best_corr: best_corr, best_key = corr, f"{notes[i]}maj"
        for i in range(12):
            corr = np.corrcoef(chroma_avg, np.roll(min_p, i))[0, 1]
            if corr > best_corr: best_corr, best_key = corr, f"{notes[i]}min"
        
        key_map = {'Cmaj':'8B','Dbmaj':'3B','Dmaj':'10B','Ebmaj':'5B','Emaj':'12B','Fmaj':'7B','F#maj':'2B','Gmaj':'9B','Abmaj':'4B','Amaj':'11B','Bbmaj':'6B','Bmaj':'1B','Amin':'8A','Bbmin':'3A','Bmin':'10A','Cmin':'5A','C#min':'12A','Dmin':'7A','D#min':'2A','Emin':'9A','Fmin':'4A','F#min':'11A','Gmin':'6A','G#min':'1A'}
        
        return {
            'bpm': float(bpm),
            'key_full': best_key,
            'camelot_key': key_map.get(best_key, best_key),
            'energy_avg': float(np.mean(rms)),
            'lufs': float(loudness),
            'duration': float(duration),
            'mix_out_point': float(mix_out_point),
            'rhythm_quality': rhythm_quality,
            'first_downbeat': float(start_offset_sec), # Cue1
            'bars_count': bars_count
        }
    except Exception as e:
        print(f"!! Fehler: {e}")
        return None
