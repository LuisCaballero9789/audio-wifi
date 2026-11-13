#!/usr/bin/env python3
"""
Audio WiFi - streams this computer's sound to a phone over the local network.

Usage:
    py audio_wifi.py            capture whatever is playing on the speakers (Windows)
    py audio_wifi.py --test     send a test tone (no capture needed)
    py audio_wifi.py --port 9000

On the phone (same Wi-Fi network): open the address shown at startup in the
browser and tap "Play".

Dependencies (only for real capture):  py -m pip install soundcard numpy
"""
import argparse
import json
import math
import queue
import socket
import struct
import sys
import threading
import time
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SAMPLE_RATE = 48000     # samples per second
CHANNELS = 2            # stereo
BLOCK = 960             # samples per block (20 ms)
QUEUE_MAX = 50          # blocks waiting per client (1 s); when full, the oldest is dropped

clients = set()
clients_lock = threading.Lock()


def broadcast(data: bytes) -> None:
    """Deliver one audio block to every connected phone."""
    with clients_lock:
        for q in clients:
            if q.full():
                try:
                    q.get_nowait()   # slow client: drop the oldest block
                except queue.Empty:
                    pass
            q.put_nowait(data)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Audio WiFi</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; min-height:100vh; display:flex; flex-direction:column; align-items:center;
         justify-content:center; gap:22px; background:#101418; color:#e8edf2;
         font-family:system-ui,sans-serif; padding:24px; box-sizing:border-box; text-align:center; }
  h1 { font-size:1.3rem; margin:0; font-weight:600; }
  button { font-size:1.25rem; padding:22px 0; width:min(320px,100%); border:0; border-radius:16px;
           background:#2f81f7; color:#fff; font-weight:600; }
  button.active { background:#c93c37; }
  #status { font-size:1rem; color:#9fb0c0; min-height:1.4em; }
  .row { width:min(320px,100%); text-align:left; font-size:.95rem; color:#c5d0da; }
  .row label { display:flex; justify-content:space-between; margin-bottom:6px; }
  input[type=range] { width:100%; }
  .chk { display:flex; gap:10px; align-items:flex-start; }
  small { color:#7d8b99; }
</style>
</head>
<body>
<h1>Computer audio</h1>
<button id="button">Play</button>
<div id="status">Stopped</div>

<div class="row">
  <label><span>Volume</span><span id="volTxt">100%</span></label>
  <input id="vol" type="range" min="0" max="100" value="100">
</div>
<div class="row">
  <label><span>Buffer (lower = less delay)</span><span id="bufTxt">80 ms</span></label>
  <input id="buf" type="range" min="40" max="400" step="20" value="80">
  <small>If the sound cuts out, raise this value.</small>
</div>
<div class="row chk">
  <input id="background" type="checkbox">
  <label for="background" style="display:block">Screen-off mode
    <br><small>Adds 1 to 3 s of delay (fine for music). Tick it before tapping Play.</small></label>
</div>
<audio id="output"></audio>

<script>
const $ = id => document.getElementById(id);
let ctx = null, gain = null, controller = null, nextTime = 0, active = false;
let received = 0, dropouts = 0;

function setStatus(t) { $('status').textContent = t; }
function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

if (load('buf')) $('buf').value = load('buf');
if (load('vol')) $('vol').value = load('vol');
if (load('background') === '1') $('background').checked = true;
const render = () => { $('bufTxt').textContent = $('buf').value + ' ms';
                       $('volTxt').textContent = $('vol').value + '%'; };
render();
$('buf').oninput = () => { render(); save('buf', $('buf').value); };
$('vol').oninput = () => { render(); save('vol', $('vol').value);
                           $('output').volume = $('vol').value / 100;
                           if (gain) gain.gain.value = $('vol').value / 100; };
$('background').onchange = () => save('background', $('background').checked ? '1' : '0');

async function start() {
  active = true;
  $('button').textContent = 'Stop';
  $('button').classList.add('active');
  setStatus('Connecting...');
  try {
    if ('mediaSession' in navigator && window.MediaMetadata) {
      navigator.mediaSession.metadata = new MediaMetadata({ title: 'Computer audio', artist: 'Audio WiFi' });
    }
    if ($('background').checked) { await startNative(); return; }
    const info = await (await fetch('/info')).json();
    const AC = window.AudioContext || window.webkitAudioContext;
    ctx = new AC({ sampleRate: info.rate, latencyHint: 'interactive' });
    gain = ctx.createGain();
    gain.gain.value = $('vol').value / 100;
    gain.connect(ctx.destination);
    await ctx.resume();
    while (active) {
      try { await receive(info); } catch (e) { if (!active) break; }
      if (!active) break;
      setStatus('Reconnecting...');
      await new Promise(r => setTimeout(r, 1000));
    }
  } catch (e) {
    setStatus('Error: ' + e.message);
    stop(true);
  }
}

// Screen-off mode: the browser plays the audio as a regular file, without
// relying on this code (which Android throttles once the screen turns off).
async function startNative() {
  const a = $('output');
  a.volume = $('vol').value / 100;
  a.src = '/audio.wav?t=' + Date.now();
  await a.play();
  setStatus('Playing (screen-off mode)');
}
let retry = null;
function reconnectNative() {
  if (!active || !$('background').checked || retry) return;
  setStatus('Reconnecting...');
  retry = setTimeout(() => {
    retry = null;
    if (active) startNative().catch(reconnectNative);
  }, 1000);
}
$('output').addEventListener('error', reconnectNative);
$('output').addEventListener('ended', reconnectNative);

async function receive(info) {
  controller = new AbortController();
  const resp = await fetch('/audio', { signal: controller.signal, cache: 'no-store' });
  const reader = resp.body.getReader();
  const bytesPerFrame = 2 * info.channels;
  let leftover = new Uint8Array(0);
  nextTime = 0;
  setStatus('Playing');
  while (active) {
    const { value, done } = await reader.read();
    if (done) break;
    let data = value;
    if (leftover.length) {
      data = new Uint8Array(leftover.length + value.length);
      data.set(leftover); data.set(value, leftover.length);
    }
    const usable = data.length - (data.length % bytesPerFrame);
    leftover = data.slice(usable);
    if (usable) schedule(data.buffer, data.byteOffset, usable, info);
  }
}

function schedule(buffer, offset, length, info) {
  const n = length / (2 * info.channels);
  const view = new DataView(buffer, offset, length);
  const margin = $('buf').value / 1000;
  const now = ctx.currentTime;

  if (nextTime < now + 0.005) {               // ran out of audio: rebuild the buffer
    if (nextTime) dropouts++;
    nextTime = now + margin;
  } else if (nextTime - now > margin + 0.25) {   // too much queued: skip ahead to avoid lagging
    nextTime = now + margin;
    return;
  }
  const ab = ctx.createBuffer(info.channels, n, info.rate);
  for (let c = 0; c < info.channels; c++) {
    const channel = ab.getChannelData(c);
    for (let i = 0; i < n; i++) channel[i] = view.getInt16((i * info.channels + c) * 2, true) / 32768;
  }
  const source = ctx.createBufferSource();
  source.buffer = ab;
  source.connect(gain);
  source.start(nextTime);
  nextTime += n / info.rate;
  if (++received % 50 === 0) {
    setStatus('Playing - approx. delay ' + Math.round((nextTime - now) * 1000 + 30) + ' ms');
  }
}

function stop(keepMessage) {
  active = false;
  if (controller) controller.abort();
  clearTimeout(retry); retry = null;
  $('output').pause(); $('output').removeAttribute('src'); $('output').load();
  if (ctx) { ctx.close(); ctx = null; }
  $('button').textContent = 'Play';
  $('button').classList.remove('active');
  if (!keepMessage) setStatus('Stopped');
}

$('button').onclick = () => active ? stop() : start();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"   # no chunked encoding: raw audio is sent until the socket closes

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._respond(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        elif path == "/info":
            body = json.dumps({"rate": SAMPLE_RATE, "channels": CHANNELS}).encode()
            self._respond(200, "application/json", body)
        elif path == "/audio":
            self._stream()
        elif path == "/audio.wav":
            self._stream(wav=True)
        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, wav=False):
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav" if wav else "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if wav:
            # "Endless" WAV header: the browser plays it like a regular audio file.
            size = 0xFFFFFFFF
            self.wfile.write(struct.pack(
                "<4sI4s4sIHHIIHH4sI", b"RIFF", size, b"WAVE", b"fmt ", 16, 1, CHANNELS,
                SAMPLE_RATE, SAMPLE_RATE * CHANNELS * 2, CHANNELS * 2, 16, b"data", size - 36))
        q = queue.Queue(maxsize=QUEUE_MAX)
        with clients_lock:
            clients.add(q)
        print(f"  + Connected: {self.client_address[0]}")
        try:
            while True:
                self.wfile.write(q.get())
                self.wfile.flush()
        except (ConnectionError, OSError):
            pass
        finally:
            with clients_lock:
                clients.discard(q)
            print(f"  - Disconnected: {self.client_address[0]}")


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # sends nothing; only finds which interface would be used
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def test_source():
    """440 Hz tone, to test the connection without capturing audio."""
    phase = 0
    step = 2 * math.pi * 440 / SAMPLE_RATE
    started = time.perf_counter()
    sent = 0
    while True:
        samples = []
        for _ in range(BLOCK):
            v = int(math.sin(phase) * 6000)
            phase += step
            samples.extend((v,) * CHANNELS)
        broadcast(struct.pack(f"<{len(samples)}h", *samples))
        sent += BLOCK
        wait = started + sent / SAMPLE_RATE - time.perf_counter()
        if wait > 0:
            time.sleep(wait)


def speaker_source(name):
    """Capture whatever is playing on the Windows audio output (WASAPI loopback)."""
    try:
        import numpy as np
        import soundcard as sc
    except ImportError:
        sys.exit("Missing dependencies. Run:\n\n    py -m pip install soundcard numpy\n")

    warnings.filterwarnings("ignore", message="data discontinuity")
    if name:
        matches = [p for p in sc.all_speakers() if name.lower() in p.name.lower()]
        if not matches:
            available = "\n".join("    " + p.name for p in sc.all_speakers())
            sys.exit(f'No audio output contains "{name}". Available:\n{available}')
        speaker = matches[0]
    else:
        speaker = sc.default_speaker()
    print(f"Capturing: {speaker.name}")
    mic = sc.get_microphone(id=str(speaker.id), include_loopback=True)
    with mic.recorder(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=BLOCK) as recorder:
        while True:
            block = recorder.record(numframes=BLOCK)
            if not clients:
                continue
            pcm = (np.clip(block, -1.0, 1.0) * 32767).astype("<i2")
            broadcast(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser(description="Stream the computer's audio to a phone over Wi-Fi.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--test", action="store_true", help="send a test tone instead of the real audio")
    ap.add_argument("--output", default="", help="part of the name of the audio output to capture")
    args = ap.parse_args()

    try:
        server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    except OSError as e:
        sys.exit(f"Could not use port {args.port} ({e}). Try --port 9000")
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print("=" * 52)
    print("  Audio WiFi is running")
    print(f"  On your phone open:  http://{local_ip()}:{args.port}")
    print("  To quit: Ctrl+C")
    print("=" * 52)
    try:
        # Capture runs on the main thread: Windows audio (COM) requires it.
        if args.test:
            test_source()
        else:
            speaker_source(args.output)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
