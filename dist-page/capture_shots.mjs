/* 抓取软件真实界面截图（起真实服务 → Playwright 驱动 → 存 dist-page/_shots/*.png → 关服务）
   用法: node token-monitor/dist-page/capture_shots.mjs                        */
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/* 站点仓库只提供 playwright-core（软件仓库没装依赖），这一处跨仓引用是刻意的 */
const require = createRequire('D:/Voyra 个人网站/package.json');
const { chromium } = require('playwright-core');

const BASE = fileURLToPath(new URL('.', import.meta.url));       /* .../token-monitor/dist-page/ */
const APP = fileURLToPath(new URL('..', import.meta.url));       /* .../token-monitor/           */
const PY = 'C:/Users/李星历/AppData/Local/Programs/Python/Python312/python.exe';
const CWD = APP.replace(/[\\/]+$/, '');
const OUT = BASE + '_shots/';
const PORT = 8422;
mkdirSync(OUT, { recursive: true });

const child = spawn(PY, ['-c',
  `import uvicorn, server\n` +
  `uvicorn.run(server.app, host="127.0.0.1", port=${PORT}, log_level="warning", http="h11", ws="none")`,
], { cwd: CWD, stdio: ['ignore', 'pipe', 'pipe'] });
child.stdout.on('data', d => process.stdout.write('[srv] ' + d));
child.stderr.on('data', d => process.stderr.write('[srv] ' + d));

const kill = () => { try { child.kill(); } catch (e) {} };
process.on('exit', kill);
process.on('SIGINT', () => { kill(); process.exit(1); });

const base = `http://127.0.0.1:${PORT}/`;
async function waitReady(maxMs = 300000) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < maxMs) {
    try {
      const r = await fetch(base + 'api/summary');
      const j = await r.json();
      const m = j._meta || {};
      last = m;
      if (m.has_data && !m.busy) return m;      /* 必须等到真有数据，否则截出来是空面板 */
    } catch (e) {}
    await new Promise(r => setTimeout(r, 1500));
  }
  throw new Error('服务/data 未就绪: ' + JSON.stringify(last));
}

const meta = await waitReady();
console.log('ready', JSON.stringify(meta));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 950 }, deviceScaleFactor: 1 });
/* 下载页是浅底，产品截图必须走软件的深色主题 —— 它是页面上唯一允许深色的东西、
   也是首屏焦点。不钉住主题就会跟着无头浏览器的系统偏好走成浅色图（实测亮度 242 vs 26）。 */
await page.addInitScript(() => { try { localStorage.setItem('tm-theme', 'dark'); } catch (e) {} });
await page.goto(base, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);

/* 时间粒度默认「今天」，切到「近 30 天」才有内容 */
try {
  await page.click('.dd-btn');
  await page.waitForTimeout(500);
  await page.getByText('近 30 天', { exact: true }).first().click();
  await page.waitForTimeout(2500);
  const label = await page.evaluate(() => document.querySelector('.dd-btn').textContent.trim());
  console.log('range =', label.replace(/\s+/g, ' '));
} catch (e) { console.log('range switch skipped:', e.message); }

async function shot(name, prep) {
  if (prep) { await prep(); await page.waitForTimeout(1500); }
  await page.screenshot({ path: OUT + name + '.png' });
  const info = await page.evaluate(() => {
    const c = document.querySelector('.content') || document.body;
    return { scrollH: c.scrollHeight, clientH: c.clientHeight };
  });
  console.log('shot', name, JSON.stringify(info));
}

await shot('overview');

await shot('models', async () => {
  await page.evaluate(() => {
    const a = document.querySelector('#nav a[data-view="models"], #nav button[data-view="models"]');
    if (a) a.click();
  });
});

await shot('settings', async () => {
  await page.click('#settingsBtn');
  await page.waitForTimeout(600);
  await page.click('.set-item[data-cat="data"]');
});

await shot('about', async () => {
  await page.click('.set-item[data-cat="about"]');
});

await browser.close();
kill();
console.log('done ->', OUT);
