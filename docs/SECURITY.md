# Security and privacy

LipScan's capture part can see video in your browser, so it's built to do as little as possible.

## What the add-on can do

- **YouTube only.** Its only host permission is `*://*.youtube.com/*`. Firefox doesn't even show it other tabs' addresses. It has no `tabs`, `<all_urls>` or `downloads` permission.
- **One video element.** It reads only the page's main `<video>`. It refuses live camera and video-call streams (anything playing a `MediaStream`).
- **Only on request.** Its page script is injected only when a recording starts.
- **No files.** It never writes files or opens anything. Recordings are streamed to the local server, which saves them.
- **Visible.** The toolbar badge shows **REC** while recording, and the popup has a Stop button. Turning the switch off disconnects and ends any recording.

## The connection

- The server listens on `127.0.0.1:8766` only, so other computers can't reach it.
- Browser pages can't connect. Only a Firefox add-on origin (`moz-extension://`) or another local copy of the server is accepted.
- **Login is a mutual challenge-response** (HMAC-SHA256) with a connection code the add-on generates. The code itself never crosses the wire, and each side must prove it knows the code before the other trusts it. A program squatting on the port learns nothing it can reuse and can't drive the add-on. There is no other login method.
- Before login, messages are capped at 8 KB, and at most 16 connections may wait to log in.

## The server

- It exposes only four tools: status, start, stop and list. It can't navigate, click, type or run code in the browser.
- It refuses tabs that aren't on YouTube. The add-on checks this as well.
- **It writes only under `%USERPROFILE%\Videos\LipScan\`.** Folder names come from the video's title, so the title is reduced to letters, digits and dashes and capped at 50 characters. Windows reserved names are avoided, and the final path is checked to still be inside that folder.
- Each recording is capped at 2 GB (`LIPSCAN_MAX_MB`). Past the cap nothing more is written, and the recording stops cleanly.
- It logs to stderr only, and nothing is sent anywhere but your own disk.

## What's tested

`test/selftest.mjs` checks, against a fake add-on:

- a wrong code is refused
- there's no plaintext login
- web pages can't connect
- the pre-login size cap
- the connection-flood guard
- non-YouTube tabs are refused, including look-alikes such as `youtube.com.evil.example` and `?u=https://www.youtube.com/`
- crafted titles (`..\..\Windows\System32`, `../../etc/passwd`, `CON`, reserved characters, 400-character titles) stay inside the recordings folder
- only one recording runs at a time
- the disk cap

## Privacy

LipScan tracks facial motion. It doesn't identify people, build face prints or compare faces. Recordings and measurements stay on your PC unless you share them.

**What the analysis saves, and what it doesn't.** Since 0.2.0, `analyze/performance.py` records the whole face. `performance.json` holds only:

- expression values: the 52 MediaPipe blendshapes, 0 to 1
- head pose: three angles, plus position in cm relative to the camera
- gaze angles per eye
- a face-detection score
- how many faces were in the frame
- frame times and file names

It **never** stores:

- MediaPipe's 478-point face mesh or any other face points (they're used in memory and thrown away)
- face crops
- face prints, identity embeddings or any other per-person signature
- anything that could be used to recognise or match a person

`face-30fps.json` (the mouth analysis) adds two normalised mouth distances, lip gap and mouth width, divided by eye distance. They are expression measures, not identifiers.

**One face only, without recognising anyone.** The face lock picks the main face by position and size only. It never compares faces, so it can't tell two people apart. That's deliberate.

Profiles and measurements are averages (rates, timings, curve shapes). They describe how someone moves, not who they are. The trace folder itself does contain the video frames you recorded; treat it like the video.

## Reporting a problem

Please open a GitHub issue, or use GitHub's private vulnerability reporting for anything sensitive.
