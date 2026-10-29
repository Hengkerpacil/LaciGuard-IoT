"""Tes sensor saja (tanpa MQTT). Jalankan di HP A dan HP B. Tutup sensor cahaya dengan jari, lalu senter. Angka lux harus berubah"""
import time
from shared import PhoneSensors

s = PhoneSensors(accel=True, light=True)
for _ in range(40):
    r = s.read()
    print(f"lux={r['lux']}   accel={r['accel']}")
    time.sleep(0.5)
