# ClipBlitz Studio, standalone

This is the phone running the studio itself: CPython, the real `clipblitz` engine, and the
engine's own web server, all inside one APK, serving the UI from `127.0.0.1`. No PC, no
LAN, no companion app.

It is a separate build from `../android`, which is the thin companion shell that drives a
PC over Wi-Fi. The companion stays the shipped APK until the milestones below are finished;
nothing here touches it or the release pipeline.

## Why Chaquopy

The engine is 4,400 lines of pure standard library Python and needs no compilation, so it
runs on CPython for Android unchanged. Chaquopy is the standard way to bundle CPython; it
is free and MIT licensed, and it is published on Maven Central as `com.chaquo.python`.
Because the engine has no pip requirements, this build resolves nothing from PyPI and there
is no native wheel to build.

## Build it

```bash
python sync-python.py     # stage the engine + web UI into app/src/main/python
cd android-standalone && gradle assembleDebug
python verify_apk.py app/build/outputs/apk/debug/app-debug.apk
```

`sync-python.py` is the only thing that puts engine code where Gradle expects it, and the
staged copy is gitignored: the studio tree stays the single source of truth.

## Milestones

| | what | state |
|---|---|---|
| M1 | CPython + the engine + its server boot on the phone, `/api/health` answers, the UI loads from `127.0.0.1` | this build |
| M2 | ffmpeg on device, so clips actually render | not started |
| M3 | yt-dlp, speech-to-text and the AI key on device | not started |
| M4 | promote this APK over the companion shell in the release | not started |

## What M1 does and does not prove

`smoke.py` runs the staged engine on the build machine through the same
`android_bootstrap.start()` the activity calls, then asks its server for `/api/health`.
`verify_apk.py` opens the built APK and proves CPython, the engine's modules and the studio
UI are really inside it.

Neither of those runs on a phone. CI has no device attached, so M1 is verified as: the code
packages, imports and serves, and the glue is exercised end to end against a real server.
The first thing that can only be seen on hardware is M2: an ffmpeg binary has to ship as a
`jniLibs` `.so` and be executed from the native library directory, because Android 10 and
later forbid executing binaries out of the app's data directory.

## Known gaps, stated plainly

- Story picking still wants an AI key and a network. Without one the engine falls back to
  its offline heuristics, which is honest but not the same edit the desktop produces.
- The engine writes to `CB_DATA` (app internal storage); it has no notion of a phone's
  gallery yet, so M3 also needs a document picker for local files.
- This APK is big and gets bigger: CPython per ABI, then ffmpeg per ABI.
