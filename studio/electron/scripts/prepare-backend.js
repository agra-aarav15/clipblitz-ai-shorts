'use strict';

/*
 * Copy the per-platform ffmpeg / ffprobe / yt-dlp binaries into the staged backend.
 * The release assets are built by eugeneware/ffmpeg-static and yt-dlp, and are
 * downloaded on the build machine so a fresh install has no external tools to find.
 *
 * electron/backend must already contain the PyInstaller server, web/, assets/ and
 * plugin/ (the workflow stages it). Run with: node scripts/prepare-backend.js
 */

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { spawnSync } = require('child_process');

const FFMPEG_TAG = 'b6.1.1';
const FFMPEG_BASE = `https://github.com/eugeneware/ffmpeg-static/releases/download/${FFMPEG_TAG}`;
const YTDLP_BASE = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download';

const platform = process.platform;
const arch = process.arch;
if (platform === 'win32' && arch !== 'x64') throw new Error('Windows builds are x64');
if (platform === 'linux' && !['x64', 'arm64'].includes(arch)) throw new Error(`unsupported Linux arch ${arch}`);
if (platform === 'darwin' && !['x64', 'arm64'].includes(arch)) throw new Error(`unsupported macOS arch ${arch}`);
const key = platform === 'win32' ? 'win32-x64' : `${platform}-${arch}`;
const ext = platform === 'win32' ? '.exe' : '';

const backend = process.env.CB_BACKEND_DIR || path.join(__dirname, '..', 'backend');
if (!fs.existsSync(backend)) {
  throw new Error(`backend staging folder is missing: ${backend}\nRun PyInstaller and stage it before this script.`);
}
const bin = path.join(backend, 'bin');
const ffdir = path.join(bin, 'ffmpeg', 'bin');
fs.mkdirSync(ffdir, { recursive: true });

async function bytes(url) {
  const res = await fetch(url, { redirect: 'follow' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${url}`);
  return Buffer.from(await res.arrayBuffer());
}

async function save(url, dest, gunzip = false) {
  const raw = await bytes(url);
  const data = gunzip ? zlib.gunzipSync(raw) : raw;
  fs.writeFileSync(dest, data);
  if (platform !== 'win32') fs.chmodSync(dest, 0o755);
  console.log(`${path.basename(dest)}: ${(data.length / 1048576).toFixed(1)} MB`);
}

async function main() {
  await save(`${FFMPEG_BASE}/ffmpeg-${key}.gz`, path.join(ffdir, `ffmpeg${ext}`), true);
  await save(`${FFMPEG_BASE}/ffprobe-${key}.gz`, path.join(ffdir, `ffprobe${ext}`), true);
  await save(`${FFMPEG_BASE}/${key}.LICENSE`, path.join(bin, 'FFMPEG-LICENSE.txt')).catch(() => {});

  const ytAsset = platform === 'win32' ? 'yt-dlp.exe'
    : platform === 'darwin' ? 'yt-dlp_macos'
      : arch === 'arm64' ? 'yt-dlp_linux_aarch64' : 'yt-dlp_linux';
  await save(`${YTDLP_BASE}/${ytAsset}`, path.join(bin, `yt-dlp${ext}`));
  await save('https://raw.githubusercontent.com/yt-dlp/yt-dlp/master/LICENSE',
    path.join(bin, 'YT-DLP-LICENSE.txt')).catch(() => {});

  const ffmpeg = path.join(ffdir, `ffmpeg${ext}`);
  const probe = spawnSync(ffmpeg, ['-version'], { encoding: 'utf8', timeout: 20000 });
  if (probe.status !== 0) throw new Error(`ffmpeg did not run: ${probe.stderr || probe.error}`);
  console.log(probe.stdout.split('\n')[0]);
  const yt = path.join(bin, `yt-dlp${ext}`);
  const ytv = spawnSync(yt, ['--version'], { encoding: 'utf8', timeout: 20000 });
  if (ytv.status !== 0) throw new Error(`yt-dlp did not run: ${ytv.stderr || ytv.error}`);
  console.log(`yt-dlp ${ytv.stdout.trim()}`);
  console.log(`prepared backend: ${backend}`);
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
