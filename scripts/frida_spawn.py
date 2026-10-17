#!/usr/bin/env python3
"""Spawn com.bjev.arcfox under Frida, load a script, stream console messages."""
import sys, time, frida

PKG = "com.bjev.arcfox"
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "scripts/frida_dump_tokens.js"
TIMEOUT = int(sys.argv[2]) if len(sys.argv) > 2 else 60

def on_message(message, data):
    if message.get("type") == "send":
        print(message["payload"], flush=True)
    elif message.get("type") == "error":
        print("ERROR:", message.get("stack") or message.get("description"), flush=True)
    else:
        print(message, flush=True)

device_id = sys.argv[3] if len(sys.argv) > 3 else 'emulator-5558'
dev = frida.get_device(device_id)
pid = dev.spawn([PKG])
print(f"spawned pid={pid}", flush=True)
session = dev.attach(pid)
script = session.create_script(open(SCRIPT).read())
script.on("message", on_message)
script.load()
dev.resume(pid)
print("resumed", flush=True)

deadline = time.time() + TIMEOUT
try:
    while time.time() < deadline:
        time.sleep(1)
except KeyboardInterrupt:
    pass
print("done", flush=True)
