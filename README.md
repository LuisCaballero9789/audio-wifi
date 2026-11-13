# Audio WiFi

Stream the sound of a Windows computer to a phone over the local Wi-Fi network. It lets you listen to your computer's audio with Bluetooth earbuds when the computer has no Bluetooth: the phone receives the sound over Wi-Fi and plays it through the earbuds.

Nothing to install on the phone: it runs in the browser. No ads, no accounts, and nothing leaves your local network.

## How it works

```
Computer (captures the sound)  --Wi-Fi-->  Phone (browser)  --Bluetooth-->  Earbuds
```

1. The script captures whatever is playing on the Windows audio output (WASAPI loopback).
2. It serves it over HTTP on the local network as 48 kHz, stereo, 16-bit PCM audio.
3. The phone opens a web page served by the same script and plays the audio.

## Requirements

- Windows 10 or 11
- Python 3.9 or later
- Computer and phone connected to the same Wi-Fi network
- A modern browser on the phone (tested with Chrome)

## Installation

```
py -m pip install -r requirements.txt
```

If you get `No module named pip`, install it first with `py -m ensurepip --upgrade`.

## Usage

1. Start the program:
   ```
   py audio_wifi.py
   ```
   You can also double-click `start.bat`, which installs the dependencies on first run.
2. If Windows Firewall asks, allow access on private networks.
3. On the phone, open the address shown in the terminal in your browser, for example `http://192.168.1.20:8000`.
4. Tap **Play**.
5. To stop the program, press `Ctrl+C` in the terminal or close the window.

### Options

| Option | What it does |
|---|---|
| `--port 9000` | Use a different port (default: 8000). |
| `--output "name"` | Capture a specific audio output instead of the default one. Part of the name is enough. |
| `--test` | Send a 440 Hz tone instead of the real audio. Useful for testing the network without relying on capture. |

## Phone controls

- **Volume:** playback volume on the phone.
- **Buffer:** how much audio is queued before playing. A low value means less delay but a higher risk of dropouts on an unstable Wi-Fi connection. If the sound cuts out, raise it.
- **Screen-off mode:** plays the audio with the browser's built-in player, which keeps working with the screen off. It adds 1 to 3 seconds of delay, so it suits music rather than video. Tick it before tapping Play.

## Latency

In normal mode, the delay inside the network is about 100 to 150 ms with the default buffer. The Bluetooth earbuds add their own delay on top, which the program cannot reduce. This is fine for music and video, but not for gaming or calls.

To reduce it: lower the buffer, use 5 GHz Wi-Fi and, if your earbuds offer one, turn on their video or low-latency mode.

## Troubleshooting

| Problem | Solution |
|---|---|
| The phone cannot load the page | Check that both devices are on the same Wi-Fi network and that Windows Firewall allows Python on private networks. |
| The page loads but there is no sound | Run `py audio_wifi.py --test`. If you hear the tone, the network works and the problem is in the capture: try `--output`. |
| The sound cuts out | Raise the buffer or move the phone closer to the router. |
| It cuts out when the screen turns off | Turn on Screen-off mode and remove the browser's battery restrictions in the phone's settings. |
| The sound also plays through the computer speakers | Turn the volume down on the speakers themselves. Muting from Windows may stop the capture on some machines. |

## Limitations

- Audio capture only works on Windows.
- It does not send the earbuds' microphone back to the computer.
- The audio travels unencrypted and without a password: anyone on the same network can open the page. Use it only on networks you trust.

## License

MIT. See the [LICENSE](LICENSE) file.
