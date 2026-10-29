import argparse, json, subprocess, time
from shared import *

ap = argparse.ArgumentParser()
ap.add_argument("--source", choices=["auto", "simulator"], default="auto")
sim = ap.parse_args().source == "simulator"

sensors = PhoneSensors(accel=True, light=True, simulator=sim)
c = make_client("edge1")


def on_connect(cl, u, f, rc, p=None):
    print("[EDGE1] MQTT terhubung:", rc)
    cl.subscribe(topic("cmd"), qos=1)


def on_message(cl, u, msg):
    try:
        cmd = json.loads(msg.payload).get("cmd")
    except ValueError:
        return
    if cmd == "FIND":  # perintah dari HP B: bunyikan HP A
        print("[EDGE1] FIND diterima, bergetar")
        if not sim:
            subprocess.Popen(["termux-vibrate", "-d", "1500"])
        cl.publish(topic("edge/edge1/ack"),
                   json.dumps({"ack": "FIND", "at_ms": int(time.time() * 1000)}),
                   qos=1)


c.on_connect, c.on_message = on_connect, on_message
c.connect(HOST, PORT, 60)
c.loop_start()
print("[EDGE1] Publish ke:", topic("edge/edge1/telemetry"))

seq = 0
while True:
    rms, lux = summarize(sensors.window())
    if rms is None or lux is None:
        print(f"[EDGE1] data sensor belum lengkap (rms={rms}, lux={lux}), dilewati")
        continue
    seq += 1
    payload = {"device_id": "edge1", "sequence": seq,
               "motion_rms": round(rms, 3), "lux": round(lux, 1),
               "sent_at_ms": int(time.time() * 1000)}
    c.publish(topic("edge/edge1/telemetry"), json.dumps(payload), qos=1)
    print("[EDGE1]", payload)
