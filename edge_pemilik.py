import argparse, json, subprocess, threading, time
from shared import *

ap = argparse.ArgumentParser()
ap.add_argument("--source", choices=["auto", "simulator"], default="auto")
sim = ap.parse_args().source == "simulator"

sensors = PhoneSensors(accel=False, light=True, simulator=sim, room=True)
c = make_client("edge2")


def alarm(text):
    print("\n[ALARM]", text)
    if not sim:  # Popen: tidak memblokir thread MQTT
        subprocess.Popen(["termux-vibrate", "-d", "1500"])
        subprocess.Popen(["termux-notification", "--title", "LaciGuard",
                          "--content", text])


def on_connect(cl, u, f, rc, p=None):
    print("[EDGE2] MQTT terhubung:", rc)
    cl.subscribe(topic("alerts"), qos=1)


def on_message(cl, u, msg):
    try:
        a = json.loads(msg.payload)
        alarm(f'{a["status"]}: {a["reason"]}')
    except (ValueError, KeyError):
        pass


c.on_connect, c.on_message = on_connect, on_message
c.connect(HOST, PORT, 60)
c.loop_start()


def sensor_loop():  # telemetri lux ruangan, jalan di thread terpisah
    seq = 0
    while True:
        _, lux = summarize(sensors.window())
        if lux is None:
            print("[EDGE2] lux belum terbaca, dilewati")
            continue
        seq += 1
        c.publish(topic("edge/edge2/telemetry"),
                  json.dumps({"device_id": "edge2", "sequence": seq,
                              "lux": round(lux, 1),
                              "sent_at_ms": int(time.time() * 1000)}), qos=1)


threading.Thread(target=sensor_loop, daemon=True).start()

# Thread utama = input perintah, jadi selalu responsif.
# a = ARM, d = DISARM, f = FIND, t = tes notifikasi lokal (tanpa detector)
keys = {"a": "ARM", "d": "DISARM", "f": "FIND"}
while True:
    k = input("[a]rm [d]isarm [f]ind [t]es notif > ").strip().lower()
    if k == "t":
        c.publish(topic("alerts"), json.dumps(
            {"status": "ALERT", "reason": "tes notifikasi"}), qos=1)
    elif k in keys:
        c.publish(topic("cmd"), json.dumps({"cmd": keys[k]}), qos=1)
        print("terkirim:", keys[k])
