'use strict';

/*
 * ClipBlitz Studio — Electron desktop shell.
 *
 * The cutting engine is the same Python backend the web studio uses. This process
 * finds a free local port, starts the bundled backend (or `python run.py` in dev),
 * waits for /api/health, then loads the studio in a native Chromium window.
 *
 * There is no terminal window and no external browser in the packaged app:
 *   Windows  ClipBlitzStudio.exe  -> ClipBlitzStudio-setup.exe
 *   macOS    ClipBlitz Studio.app
 *   Linux    ClipBlitzStudio-*.AppImage
 *
 * User data (clips, jobs, provider keys, logs) goes to Electron's userData folder,
 * never inside the app bundle. That keeps the app update-safe and writable on macOS.
 */

const { app, BrowserWindow, Menu, dialog, shell } = require('electron');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

const APP_NAME = 'ClipBlitz Studio';
const IS_WIN = process.platform === 'win32';
const IS_MAC = process.platform === 'darwin';
const SELF_TEST = process.env.CB_SELF_TEST === '1' || process.argv.includes('--self-test');
const DEV_TOOLS = process.argv.includes('--devtools') || process.env.CB_DEVTOOLS === '1';

// A product name must be set before asking Electron for userData, otherwise the
// folder is named after package.json's slug on first run.
app.setName(APP_NAME);
if (SELF_TEST) app.disableHardwareAcceleration();

let backend = null;
let backendError = '';
let backendLog = '';
let backendExited = false;
let mainWindow = null;
let splashWindow = null;
let port = 0;
let dataDir = '';
let appLog = '';
let quitting = false;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function appendLog(chunk) {
  const text = String(chunk || '');
  if (!text) return;
  backendLog = (backendLog + text).slice(-24000);
  if (SELF_TEST) {
    process.stdout.write(text);
    return;
  }
  try {
    fs.appendFileSync(appLog, text);
  } catch {
    /* logging must never kill the app */
  }
}

function backendDir() {
  const override = process.env.CB_BACKEND;
  if (override) {
    try {
      return fs.statSync(override).isDirectory() ? override : path.dirname(override);
    } catch {
      return path.dirname(override);
    }
  }
  if (app.isPackaged) return path.join(process.resourcesPath, 'backend');
  return path.join(__dirname, '..');
}

function backendExecutable() {
  const exe = IS_WIN ? 'ClipBlitzStudio-server.exe' : 'ClipBlitzStudio-server';
  const override = process.env.CB_BACKEND;
  if (override) {
    try {
      return fs.statSync(override).isDirectory() ? path.join(override, exe) : override;
    } catch {
      return override;
    }
  }
  if (app.isPackaged) return path.join(process.resourcesPath, 'backend', exe);
  return '';
}

function portFree(p) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => server.close(() => resolve(true)));
    server.listen(p, '127.0.0.1');
  });
}

async function choosePort(preferred) {
  if (preferred) {
    for (const p of [preferred, preferred + 1, preferred + 2, preferred + 10]) {
      if (await portFree(p)) return p;
    }
  }
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const p = server.address().port;
      server.close(() => resolve(p));
    });
  });
}

function httpGet(pathname, timeout = 1500) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: '127.0.0.1', port, path: pathname, timeout },
      (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => { body += chunk; });
        res.on('end', () => resolve({ status: res.statusCode || 0, body }));
      },
    );
    req.on('timeout', () => req.destroy());
    req.on('error', () => resolve({ status: 0, body: '' }));
  });
}

async function waitForHealth(ms = 60000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const res = await httpGet('/api/health', 900);
    if (res.status === 200 && res.body.includes('ClipBlitz')) return true;
    if (backendExited) return false;
    await sleep(350);
  }
  return false;
}

function startBackend() {
  const exe = backendExecutable();
  const cwd = backendDir();
  const env = {
    ...process.env,
    CB_DATA: dataDir,
    CB_PORT: String(port),
    PYTHONUNBUFFERED: '1',
    PYTHONIOENCODING: 'utf-8',
  };

  let command = exe;
  let args = [String(port)];
  if (!command) {
    command = process.env.PYTHON || (IS_WIN ? 'python' : 'python3');
    args = [path.join(__dirname, '..', 'run.py'), String(port)];
  } else if (!fs.existsSync(command)) {
    throw new Error(
      `The bundled backend is missing:\n${command}\n\n` +
      'Run the Electron build from GitHub Actions, or set CB_BACKEND to a built ' +
      'ClipBlitzStudio-server binary.',
    );
  }

  appendLog(`\n[desktop] starting ${command} ${args.join(' ')}\n[desktop] data ${dataDir}\n`);
  backend = spawn(command, args, {
    cwd,
    env,
    windowsHide: true,
    detached: !IS_WIN,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  backend.on('error', (err) => {
    backendError = err.message;
    appendLog(`[desktop] backend error: ${err.message}\n`);
  });
  backend.stdout.on('data', appendLog);
  backend.stderr.on('data', appendLog);
  backend.on('exit', (code, signal) => {
    backendExited = true;
    appendLog(`[desktop] backend exited code=${code} signal=${signal}\n`);
    if (!quitting && code !== 0) backendError = `backend exited with ${code}`;
  });
}

function stopBackend() {
  quitting = true;
  if (!backend) return;
  const child = backend;
  backend = null;
  const pid = child.pid;
  try {
    if (IS_WIN) {
      spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true });
    } else {
      process.kill(-pid, 'SIGTERM');
    }
  } catch {
    try { child.kill(); } catch { /* already gone */ }
  }
}

function openDoc(name) {
  const local = path.join(backendDir(), name);
  if (fs.existsSync(local)) {
    shell.openPath(local);
    return;
  }
  const base = 'https://github.com/agra-aarav15/clipblitz-ai-shorts/blob/main/studio/';
  shell.openExternal(base + name);
}

function showAbout() {
  dialog.showMessageBox(mainWindow || undefined, {
    type: 'info',
    title: `About ${APP_NAME}`,
    message: `${APP_NAME} ${app.getVersion()}`,
    detail:
      'The cutting desk for the internet’s best 30 seconds.\n\n' +
      `Backend: ${backendExecutable() || 'python run.py (dev)'}\n` +
      `Electron: ${process.versions.electron}  Chromium: ${process.versions.chrome}\n` +
      `Data: ${dataDir}`,
    buttons: ['Good'],
  });
}

function buildMenu() {
  const template = [];
  if (IS_MAC) {
    template.push({
      role: 'appMenu',
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { label: 'Open data folder', click: () => shell.openPath(dataDir) },
        { label: 'Open backend log', click: () => shell.openPath(appLog) },
        { type: 'separator' },
        { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
        { type: 'separator' }, { role: 'quit' },
      ],
    });
  }
  template.push({
    label: 'File',
    submenu: [
      { label: 'Open data folder', accelerator: 'CmdOrCtrl+Shift+D', click: () => shell.openPath(dataDir) },
      { label: 'Open backend log', click: () => shell.openPath(appLog) },
      { type: 'separator' },
      { label: 'Setup guide', click: () => openDoc('SETUP.md') },
      { label: 'YouTube setup', click: () => openDoc('SETUP-YOUTUBE.md') },
      { type: 'separator' },
      { role: IS_MAC ? 'close' : 'quit' },
    ],
  });
  template.push({ role: 'editMenu' });
  template.push({
    label: 'View',
    submenu: [
      { role: 'reload' },
      { role: 'forceReload' },
      { role: 'toggleDevTools', visible: DEV_TOOLS },
      { type: 'separator' },
      { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
      { type: 'separator' },
      { role: 'togglefullscreen' },
    ],
  });
  template.push({
    label: 'Help',
    submenu: [
      { label: 'Project README', click: () => openDoc('README.md') },
      { label: 'Report an issue', click: () => shell.openExternal('https://github.com/agra-aarav15/clipblitz-ai-shorts/issues') },
      { type: 'separator' },
      { label: `About ${APP_NAME}`, click: showAbout },
    ],
  });
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 520,
    height: 320,
    frame: false,
    resizable: false,
    movable: true,
    alwaysOnTop: true,
    show: true,
    center: true,
    backgroundColor: '#050505',
    skipTaskbar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
  splashWindow.on('closed', () => { splashWindow = null; });
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
  splashWindow = null;
}

function createMainWindow() {
  const icon = path.join(__dirname, 'build', 'icon.png');
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1040,
    minHeight: 680,
    show: false,
    backgroundColor: '#050505',
    title: APP_NAME,
    icon: fs.existsSync(icon) ? icon : undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  });

  const base = `http://127.0.0.1:${port}`;
  const isLocal = (url) => url.startsWith(base + '/') || url === base;

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isLocal(url)) {
      event.preventDefault();
      if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    }
  });
  mainWindow.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
    if (!isMainFrame) return;
    appendLog(`[desktop] page failed ${code} ${description} ${url}\n`);
  });
  mainWindow.once('ready-to-show', () => {
    closeSplash();
    mainWindow.show();
    mainWindow.focus();
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  mainWindow.loadURL(base + '/');
}

function fail(message) {
  const detail = backendError ? `${message}\n\n${backendError}` : message;
  appendLog(`[desktop] ${detail}\n`);
  if (SELF_TEST) {
    console.error(detail);
    process.exitCode = 1;
    stopBackend();
    app.quit();
    return;
  }
  dialog.showErrorBox(`${APP_NAME} could not start`, detail);
  stopBackend();
  app.quit();
}

async function bootstrap() {
  dataDir = app.getPath('userData');
  fs.mkdirSync(dataDir, { recursive: true });
  appLog = path.join(dataDir, 'backend.log');
  app.setAppUserModelId('com.clipblitz.studio');

  try {
    port = await choosePort(SELF_TEST ? 0 : 4300);
  } catch (err) {
    fail(`Could not find a local port: ${err.message}`);
    return;
  }

  if (!SELF_TEST) createSplash();
  try {
    startBackend();
  } catch (err) {
    fail(err.message);
    return;
  }

  const healthy = await waitForHealth(SELF_TEST ? 90000 : 60000);
  if (!healthy) {
    fail(
      'The local engine did not answer /api/health.\n\n' +
      `Port: ${port}\nLog: ${appLog}\n\n` +
      'If you are running from source, start it with: python run.py 4300',
    );
    return;
  }

  if (SELF_TEST) {
    const page = await httpGet('/', 5000);
    const ok = page.status === 200 && /ClipBlitz/i.test(page.body);
    console.log(`electron self-test: health ok, page ${ok ? 'ok' : 'missing'}, port ${port}`);
    stopBackend();
    if (!ok) process.exitCode = 1;
    app.quit();
    return;
  }

  buildMenu();
  createMainWindow();
}

const gotLock = SELF_TEST ? true : app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  app.on('before-quit', stopBackend);
  app.on('window-all-closed', () => { if (!SELF_TEST) app.quit(); });
  app.on('activate', () => {
    if (mainWindow) mainWindow.show();
    else if (!SELF_TEST && dataDir) createMainWindow();
  });
  app.whenReady().then(bootstrap).catch((err) => fail(err.message));
}
