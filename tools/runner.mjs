/** Open-source browser scanner bridge. Inputs are deployment-owned JSON files. */
import fs from 'node:fs/promises';
import puppeteer from 'puppeteer';

const [mode, file] = process.argv.slice(2);
if (!['lighthouse', 'pa11y'].includes(mode) || !file) throw new Error('Unsupported scanner');
const config = JSON.parse(await fs.readFile(file, 'utf8'));
const targetOrigin = new URL(config.url).origin;
if (!config.proxy || !config.chromium) throw new Error('Mandatory outbound guard/browser is missing');
const browser = await puppeteer.launch({
  executablePath: config.chromium,
  headless: true,
  acceptInsecureCerts: true,
  ignoreHTTPSErrors: true, // Trust only the local MITM certificate; upstream TLS is verified by the guard.
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--ignore-certificate-errors',
    `--proxy-server=${config.proxy}`, '--proxy-bypass-list=<-loopback>',
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'],
});
const unsafe = /(?:^|[/_.\-])(?:delete|remove|destroy|logout|reset|revoke|purchase|pay|checkout|register|signup|upload|shutdown)(?:$|[/_.\-])/i;
async function safePage(page) {
  await page.setBypassServiceWorker(true);
  await page.setRequestInterception(true);
  page.on('request', request => {
    if (request.isInterceptResolutionHandled()) return;
    try {
      const url = new URL(request.url());
      if (['data:', 'blob:'].includes(url.protocol)) return void request.continue();
      if (url.origin !== targetOrigin || !['GET', 'HEAD', 'OPTIONS'].includes(request.method()) || unsafe.test(decodeURIComponent(url.pathname)))
        return void request.abort('blockedbyclient');
      return void request.continue();
    } catch { return void request.abort('blockedbyclient'); }
  });
}
try {
  const page = await browser.newPage();
  await safePage(page);
  if (mode === 'pa11y') {
    const { default: pa11y } = await import('pa11y');
    // Long-polling/SPAs need not reach networkidle. Reuse a bounded, safely navigated page.
    await page.goto(config.url, {waitUntil:'domcontentloaded', timeout:Math.min(config.timeout,20000)});
    const result = await pa11y(config.url, {
      browser, page, standard: 'WCAG2AA', runners: ['htmlcs'], timeout: config.timeout,
      ignoreUrl:true, wait: 750, ignore: [], includeWarnings: true, includeNotices: false,
    });
    console.log(JSON.stringify({issues:result.issues,documentTitle:result.documentTitle}));
  } else {
    const { default: lighthouse } = await import('lighthouse');
    const port = Number(new URL(browser.wsEndpoint()).port);
    const result = await lighthouse(config.url, {
      port, output: 'json', logLevel: 'error', onlyCategories: ['performance'],
      maxWaitForLoad: 20000, maxWaitForFcp: 15000,
      disableStorageReset: true,
    }, undefined, page);
    const lhr = result.lhr;
    const ids = ['largest-contentful-paint', 'cumulative-layout-shift', 'total-blocking-time',
      'first-contentful-paint', 'speed-index', 'server-response-time'];
    console.log(JSON.stringify({
      version: lhr.lighthouseVersion, score: Math.round(lhr.categories.performance.score * 100),
      runtimeError: lhr.runtimeError || null, warnings: lhr.runWarnings || [],
      audits: Object.fromEntries(ids.map(id => [id, lhr.audits[id]])),
      screenshot: lhr.audits['final-screenshot']?.details?.data || null,
    }));
  }
} finally {
  await browser.close();
}
