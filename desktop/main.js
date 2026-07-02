// flipped 桌面壳(M6.8)。主进程:静态服务 Console 构建产物 + 拉起后端 + 开窗。
// 链路仍是 Console → 后端(:8011,exo 直连)→ OpenHands 沙盒(:8000)。
const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const ROOT = path.join(__dirname, '..');
const DIST = path.join(ROOT, 'console', 'dist');
const BACKEND_PORT = process.env.FLIPPED_BACKEND_PORT || '8011';
const STATIC_PORT = Number(process.env.FLIPPED_STATIC_PORT || 5399);
const EXO = process.env.FLIPPED_MODEL_BASE_URL || 'http://100.64.201.37:52415/v1';

const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.woff2': 'font/woff2', '.woff': 'font/woff', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
};

let backendProc = null;
let staticServer = null;

function serveStatic() {
  staticServer = http
    .createServer((req, res) => {
      let p = decodeURIComponent((req.url || '/').split('?')[0]);
      if (p === '/') p = '/index.html';
      let file = path.join(DIST, p);
      if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(DIST, 'index.html'); // SPA fallback
      fs.readFile(file, (err, data) => {
        if (err) {
          res.writeHead(404);
          res.end('not found');
          return;
        }
        res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
        res.end(data);
      });
    })
    .listen(STATIC_PORT, '127.0.0.1');
}

function startBackend() {
  // 已有后端则不重复起
  const probe = http.get(`http://127.0.0.1:${BACKEND_PORT}/api/v1/sessions`, () => probe.destroy());
  probe.on('error', () => {
    const py = process.env.FLIPPED_PYTHON || path.join(ROOT, '.venv', 'bin', 'python');
    backendProc = spawn(py, ['-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', BACKEND_PORT], {
      cwd: ROOT,
      env: {
        ...process.env,
        PYTHONPATH: 'src',
        EXO_API_KEY: process.env.EXO_API_KEY || 'dummy',
        OPENHANDS_AGENT_HOST: process.env.OPENHANDS_AGENT_HOST || 'http://localhost:8000',
        FLIPPED_MODEL_BASE_URL: EXO,
        NO_PROXY: '100.64.201.37,localhost,127.0.0.1,::1',
      },
      stdio: 'inherit',
    });
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    backgroundColor: '#0f0f10',
    title: 'flipped',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true },
  });
  win.loadURL(`http://127.0.0.1:${STATIC_PORT}/`);
}

app.whenReady().then(() => {
  if (!fs.existsSync(path.join(DIST, 'index.html'))) {
    console.error('缺 console/dist —— 请先 (cd console && npm run build)');
  }
  serveStatic();
  startBackend();
  setTimeout(createWindow, 900); // 给后端/静态服务一点启动时间
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
app.on('quit', () => {
  try {
    if (backendProc) backendProc.kill();
  } catch (_e) { /* ignore */ }
  if (staticServer) staticServer.close();
});
