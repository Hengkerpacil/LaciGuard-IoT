import json, math, os, random, subprocess, threading, time
from statistics import median
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()
PROJECT_ID = os.getenv("PROJECT_ID", "laciguard_kelompok_XX")
HOST = os.getenv("MQTT_HOST", "broker.hivemq.com")
PORT = int(os.getenv("MQTT_PORT", "8883"))
GRAVITY, WINDOW = 9.81, 5
SAMPLE_S = 0.25  # jeda antar sampel dalam satu window


def topic(suffix):
    return f"laciguard/{PROJECT_ID}/{suffix}"


def make_client(name):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"{name}-{random.randint(1000, 9999)}")
    c.tls_set()  # MQTT over TLS
    c.reconnect_delay_set(1, 10)
    return c


def _find(names, key, exclude=("uncalibrated",)):
    c = [n for n in names if key in n.lower()
         and not any(x in n.lower() for x in exclude)]
    c.sort(key=lambda n: "non-wakeup" not in n.lower())
    if not c:
        raise RuntimeError(f"Sensor '{key}' tidak ditemukan. Daftar: {names}")
    return c[0]


class PhoneSensors:
    """Baca sensor HP lewat Termux:API (mode STREAM), atau simulasi.

    Kenapa stream? `termux-sensor -n 1` memulai sensor lalu langsung
    mematikannya. Sensor cahaya bersifat on-change, jadi sering belum sempat
    melapor dan hasilnya 0.0 / basi. Dengan stream, sensor dibiarkan menyala
    dan kita tinggal ambil nilai terbaru."""

    def __init__(self, accel=True, light=True, simulator=False, room=False):
        self.sim, self.room = simulator, room
        self.n_acc = self.n_lux = None
        self.latest, self.stamp = {}, {}
        self.lock = threading.Lock()
        if simulator:
            return
        names = json.loads(subprocess.run(
            ["termux-sensor", "-l"], capture_output=True, text=True,
            timeout=12, check=True).stdout)["sensors"]
        if accel:
            self.n_acc = _find(names, "accelerometer",
                               ("uncalibrated", "limited"))
        if light:
            self.n_lux = _find(names, "light", ("uncalibrated", "flicker"))
        print(f"[SENSOR] accel={self.n_acc} | light={self.n_lux}")
        wanted = [n for n in (self.n_acc, self.n_lux) if n]
        self.proc = subprocess.Popen(
            ["termux-sensor", "-s", ",".join(wanted), "-d", "200"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        threading.Thread(target=self._reader, daemon=True).start()
        self.wait_ready()

    def _reader(self):
        dec, buf = json.JSONDecoder(), ""
        for line in self.proc.stdout:
            buf += line
            while True:
                buf = buf.lstrip()
                if not buf:
                    break
                try:
                    obj, end = dec.raw_decode(buf)
                except json.JSONDecodeError:
                    break  # objek JSON belum lengkap, tunggu baris berikut
                buf = buf[end:]
                now = time.time()
                with self.lock:
                    for name, v in obj.items():
                        vals = v.get("values") if isinstance(v, dict) else None
                        if vals:
                            self.latest[name] = [float(x) for x in vals]
                            self.stamp[name] = now

    def wait_ready(self, timeout=6):
        need = [n for n in (self.n_acc, self.n_lux) if n]
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if all(n in self.latest for n in need):
                    return True
            time.sleep(0.2)
        with self.lock:
            missing = [n for n in need if n not in self.latest]
        print(f"[SENSOR] PERINGATAN: belum ada data dari {missing}. "
              "Layar HP harus menyala dan Termux:API diberi izin.")
        return False

    def read(self):
        if self.sim:
            scen = os.getenv("SIM_SCENARIO", "still")  # still|open|nudge|breach
            moving = scen in ("nudge", "breach")
            opened = scen in ("open", "breach")
            s = 5.0 if moving else 0.02
            lux = 120 if (self.room or opened) else 2
            return {"accel": (random.gauss(0, s), random.gauss(0, s),
                              9.81 + random.gauss(0, s)),
                    "lux": max(0.0, random.gauss(lux, lux * 0.03 + 0.3))}
        now = time.time()
        with self.lock:
            acc = self.latest.get(self.n_acc) if self.n_acc else None
            if acc and now - self.stamp[self.n_acc] > 3:
                acc = None  # accelerometer harusnya terus mengalir; kalau basi, anggap mati
            lux = self.latest.get(self.n_lux) if self.n_lux else None
        return {"accel": tuple(acc[:3]) if acc else None,
                "lux": lux[0] if lux else None}

    def window(self):
        out = []
        for _ in range(WINDOW):
            out.append(self.read())
            time.sleep(SAMPLE_S)
        return out


def motion_rms(accels):  # processing A: RMS getaran
    errs = [math.sqrt(x * x + y * y + z * z) - GRAVITY for x, y, z in accels]
    return math.sqrt(sum(e * e for e in errs) / len(errs))


def lux_median(values):  # processing B: filter median cahaya
    return median(values)


def summarize(win):
    """Hasilkan (rms, lux) dari satu window; None kalau datanya kosong."""
    acc = [w["accel"] for w in win if w["accel"]]
    lux = [w["lux"] for w in win if w["lux"] is not None]
    return (motion_rms(acc) if acc else None,
            lux_median(lux) if lux else None)
