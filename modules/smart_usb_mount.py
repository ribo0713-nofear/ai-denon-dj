import subprocess
import os

class SmartUSBMount:
    def __init__(self, mount_point="/mnt/denon"):
        self.mount_point = mount_point
        self.device = None
        self.last_error = ""

    def find_usb_device(self):
        """
        Sucht nach dem Stick mit der 'Flat-List' Logik (-l),
        um Baum-Grafiken (wie └─) zu vermeiden.
        """
        try:
            # -l steht für 'list' (flaches Format ohne Baum-Grafik)
            # -n für keine Überschriften
            # -p für vollen Pfad (/dev/sda1 statt sda1)
            cmd = "lsblk -lnpo NAME,RM,TYPE,FSTYPE"
            output = subprocess.check_output(cmd, shell=True).decode().splitlines()
            
            for line in output:
                parts = line.split()
                if len(parts) < 3: continue
                
                # Jetzt sind die Pfade sauber, z.B. '/dev/sda1'
                name = parts[0]
                is_removable = parts[1] == "1"
                is_partition = parts[2] == "part"
                
                if is_removable and is_partition:
                    self.device = name
                    return self.device
            
            self.last_error = "Kein wechselbarer Datenträger gefunden."
            return None
        except Exception as e:
            self.last_error = f"Hardware-Suche Fehler: {str(e)}"
            return None

    def mount(self):
        device = self.find_usb_device()
        if not device:
            return False, self.last_error

        # 1. Mount-Punkt aufräumen
        if not os.path.exists(self.mount_point):
            subprocess.run(["sudo", "mkdir", "-p", self.mount_point])
        
        # Sicherstellen, dass der Ordner dir gehört, falls der Mount fehlschlägt
        subprocess.run(["sudo", "chown", "1000:1000", self.mount_point])

        # Aushängen erzwingen
        subprocess.run(["sudo", "umount", "-l", self.mount_point], stderr=subprocess.DEVNULL)

        # 2. Der saubere Mount-Befehl
        mount_cmd = [
            "sudo", "mount", device, self.mount_point,
            "-o", "rw,uid=1000,gid=1000,umask=000,nofail"
        ]
        
        result = subprocess.run(mount_cmd)
        
        if result.returncode == 0:
            return self.health_check()
        else:
            return False, f"Mount fehlgeschlagen für {device}. Prüfe Dateisystem!"

    def health_check(self):
        test_file = os.path.join(self.mount_point, ".write_test")
        try:
            with open(test_file, "w") as f:
                f.write("Aron-Fix-Test")
            os.remove(test_file)
            return True, f"Stick {self.device} ist jetzt RW (Schreibbar) bereit!"
        except Exception as e:
            return False, f"SCHREIBFEHLER auf {self.device}: {str(e)}"
