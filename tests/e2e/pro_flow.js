#!/usr/bin/env node
/*
 * End-to-end checks for the Pro features, by role, against a RUNNING server.
 *
 *   node tests/e2e/pro_flow.js
 *
 * Covers: logins for every role, two-step login (TOTP, recovery codes, replay, policy), idle timeout,
 * sign out other devices, OIDC when not configured; Diagnostics (lab pipeline, critical call-out with
 * read-back and escalation, reflex rule, reference ranges, radiology with PCPNDT Form F, pharmacy FEFO
 * and Schedule H register, double-submit); Command Centre and wall mode; notifications bell; AI Labs
 * (agents, findings Accept / Dismiss, human-in-the-loop); AI features (no-show risk pills, draft
 * replies, coding assistant, NEWS2 vitals and alerts, report explainers in /my); voice agent
 * (/voice/demo and /my/voice). Every area has negative checks (wrong role, other branch, bad input).
 *
 * Environment (defaults match docs/TEST_PLAN.md, Pro section):
 *   E2E_BASE_URL   http://127.0.0.1:8021
 *   TT_DB_PATH     the server's SQLite file (read to pick records, read OTPs and TOTP secrets, check money)
 *   E2E_PASSWORD   Qa@12345 (all QA logins)
 *   E2E_SHOTS      directory for failure screenshots
 *   E2E_HEADED=1   watch the browser
 *
 * Needs a fresh seed plus these logins (all with E2E_PASSWORD): admin (no branch), owner (no branch),
 * doctor, nurse, lab, pharmacy, billing (branch A), frontb (front desk, branch B).
 * Selectors use roles, labels and visible text. Hidden form fields are read by name only to build
 * the negative POSTs that a browser form would never send (missing read-back, missing Form F).
 * Prints PASS / FAIL / SKIP per step; exits 1 if any step fails.
 */
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const BASE = (process.env.E2E_BASE_URL || 'http://127.0.0.1:8021').replace(/\/$/, '');
const DB = process.env.TT_DB_PATH || '';
const PASSWORD = process.env.E2E_PASSWORD || 'Qa@12345';
const SHOTS = process.env.E2E_SHOTS ||
  '/tmp/claude-0/-home-user/5f540028-1c92-5b5c-889b-342c486a270d/scratchpad/qa-pro-shots';
const ROOT = path.resolve(__dirname, '..', '..');
const results = [];
const serverErrors = [];
const RUN = String(Date.now()).slice(-6);

// ---------------------------------------------------------------- helpers

function sql(query, params = []) {
  if (!DB) throw new Error('TT_DB_PATH is not set');
  const py = [
    'import json, sqlite3, sys',
    'c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)',
    'c.row_factory = sqlite3.Row',
    'print(json.dumps([dict(r) for r in c.execute(sys.argv[2], json.loads(sys.argv[3]))]))',
  ].join('\n');
  return JSON.parse(execFileSync('python3', ['-c', py, DB, query, JSON.stringify(params)], { encoding: 'utf8' }));
}
const one = (q, p) => sql(q, p)[0];

/** Run Python inside the app (same database) for time travel and cookie forging. Last stdout line is JSON. */
function py(code) {
  const out = execFileSync('python3', ['-c', code], {
    encoding: 'utf8', cwd: ROOT, env: { ...process.env, TT_DB_PATH: DB, TT_SCHEDULER: 'off' },
  });
  return JSON.parse(out.trim().split('\n').pop());
}

function expect(cond, msg) { if (!cond) throw new Error(msg); }

async function step(page, name, fn) {
  const t0 = Date.now();
  try {
    const note = await fn();
    if (note && String(note).startsWith('SKIP')) {
      results.push({ name, status: 'SKIP', note });
      console.log(`SKIP  ${name} - ${String(note).slice(5)}`);
    } else {
      results.push({ name, status: 'PASS', note });
      console.log(`PASS  ${name}${note ? ' - ' + note : ''} (${Date.now() - t0} ms)`);
    }
  } catch (e) {
    const file = path.join(SHOTS, `pro-fail-${String(results.length + 1).padStart(2, '0')}-${name.replace(/[^a-z0-9]+/gi, '_').slice(0, 60)}.png`);
    try { await page.screenshot({ path: file, fullPage: true }); } catch (_) { /* page may be gone */ }
    const msg = (e && e.message ? e.message : String(e)).split('\n')[0];
    results.push({ name, status: 'FAIL', note: msg, screenshot: file });
    console.log(`FAIL  ${name} - ${msg}\n      url: ${page.url()}\n      screenshot: ${file}`);
  }
}

// RFC 6238 TOTP, same maths as app/twofactor.py.
function b32(s) {
  const al = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const ch of s.replace(/=+$/, '').toUpperCase()) bits += al.indexOf(ch).toString(2).padStart(5, '0');
  const out = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(out);
}
function hotp(secret, counter) {
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const d = crypto.createHmac('sha1', b32(secret)).update(buf).digest();
  const o = d[d.length - 1] & 0x0f;
  return String((d.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, '0');
}
/** A code the server will accept now: the earliest step in the +-1 window newer than the last used one. */
function freshCode(username) {
  const u = one('SELECT totp_secret, totp_last_step FROM users WHERE username = ?', [username]);
  const now = Math.floor(Date.now() / 1000 / 30);
  for (const s of [now - 1, now, now + 1]) if (s > (u.totp_last_step || 0)) return { code: hotp(u.totp_secret, s), step: s };
  throw new Error('no unused TOTP step in the window');
}

async function flash(page) {
  const read = async role => {
    const loc = page.locator(`[aria-live] [role=${role}]`);
    return (await loc.count()) ? (await loc.allInnerTexts()).join(' ').trim() : '';
  };
  try { await page.locator('[aria-live] [role=status], [aria-live] [role=alert]').first().waitFor({ state: 'attached', timeout: 3000 }); } catch (_) { /* none */ }
  return { msg: await read('status'), err: await read('alert') };
}

const text = page => page.locator('body').innerText();

/** Type a patient message into the Messages simulator (demo mode only) and send it. */
async function simulate(page, phone, msg) {
  const form = page.getByRole('form', { name: /simulate a patient message/i });
  if (!(await form.isVisible())) await page.getByText(/simulate a patient message/i).first().click();
  await form.getByLabel(/patient mobile/i).fill(phone);
  await form.getByLabel(/^message$/i).fill(msg);
  const [resp] = await Promise.all([
    page.waitForResponse(r => r.url().includes('/webhooks/simulate-inbound') && r.request().method() === 'POST'),
    form.getByRole('button', { name: /send as patient/i }).click(),
  ]);
  await page.waitForLoadState('domcontentloaded');
  if (resp.status() >= 400) throw new Error(`simulator POST returned ${resp.status()}`);
}

async function newRolePage(browser, viewport = { width: 1280, height: 900 }) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  page.setDefaultTimeout(10000);
  page.on('response', r => { if (r.status() >= 500) serverErrors.push(`${r.status()} ${r.url()}`); });
  page.on('pageerror', e => serverErrors.push(`JS error on ${page.url()}: ${e.message}`));
  return page;
}

/** Staff login through the form; answers the second step with a fresh TOTP if the user has it on. */
async function login(page, username, password = PASSWORD) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.waitForLoadState('domcontentloaded');
  if (new URL(page.url()).pathname === '/login/2fa') {
    await page.getByLabel(/6-digit code/i).fill(freshCode(username).code);
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.waitForLoadState('domcontentloaded');
  }
  return page;
}

/** POST a form with this page's CSRF token, the way a crafted request (or an old tab) would. */
async function post(page, url, form = {}) {
  const csrf = await page.locator('input[name="csrf"]').first().inputValue();
  const r = await page.request.post(BASE + url, { form: { csrf, ...form } });
  return { status: r.status(), body: await r.text(), url: r.url() };
}

async function navLinks(page) {
  const nav = page.getByRole('navigation');
  return (await nav.getByRole('link').allInnerTexts()).map(s => s.trim()).filter(Boolean);
}

const phoneFor = n => `9${String(70000000 + Number(RUN) * 10 + n).padStart(9, '0').slice(-9)}`;

// ---------------------------------------------------------------- flow

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ headless: process.env.E2E_HEADED !== '1' });
  const admin = await newRolePage(browser);
  const st = {};   // values shared between steps

  await step(admin, 'P00 server up, login page loads', async () => {
    const r = await admin.goto(`${BASE}/login`);
    expect(r && r.status() === 200, `GET /login returned ${r && r.status()}`);
    expect(DB, 'TT_DB_PATH is not set');
  });

  // ------------------------------------------------ logins and roles
  const HOMES = { admin: '/', owner: '/', doctor: '/appointments', nurse: '/appointments', frontb: '/leads',
    billing: '/billing', lab: '/diagnostics', pharmacy: '/diagnostics' };
  const pages = { admin };
  for (const [u, home] of Object.entries(HOMES)) {
    await step(admin, `P01 ${u} logs in and the home screen opens`, async () => {
      const p = pages[u] || (pages[u] = await newRolePage(browser));
      const resp = [];
      const h = r => { if (r.request().resourceType() === 'document') resp.push(r.status()); };
      p.on('response', h);
      await login(p, u);
      p.off('response', h);
      expect(new URL(p.url()).pathname === home, `landed on ${p.url()}, expected ${home}`);
      const last = resp[resp.length - 1];
      expect(last === 200, `home screen ${home} answered HTTP ${last} for role ${u}: "${(await text(p)).split('\n').find(l => /access|expired/i.test(l)) || ''}"`);
    });
  }

  await step(admin, 'P02 role matrix: wrong role gets 403 and no menu link', async () => {
    const checks = [['nurse', '/command'], ['nurse', '/ai-labs'], ['billing', '/vitals'], ['lab', '/ai-labs'],
      ['frontb', '/explainers'], ['frontb', '/command'], ['doctor', '/billing'], ['owner', '/vitals'], ['doctor', '/ai-labs']];
    const bad = [];
    for (const [u, url] of checks) {
      const r = await pages[u].goto(BASE + url);
      if (r.status() !== 403) bad.push(`${u} ${url} -> ${r.status()}`);
      else if (!/don't have access/i.test(await text(pages[u]))) bad.push(`${u} ${url} 403 without the access message`);
    }
    const nurseNav = await (async () => { await pages.nurse.goto(`${BASE}/appointments`); return navLinks(pages.nurse); })();
    if (nurseNav.some(l => /command centre|ai labs/i.test(l))) bad.push(`nurse menu shows ${nurseNav.join(', ')}`);
    await pages.owner.goto(`${BASE}/`);
    const ownerNav = await navLinks(pages.owner);
    if (!ownerNav.some(l => /ai labs/i.test(l)) || !ownerNav.some(l => /command centre/i.test(l))) bad.push(`owner menu lacks AI Labs / Command Centre: ${ownerNav.join(', ')}`);
    expect(!bad.length, bad.join('; '));
    return `${checks.length} denials + menus`;
  });

  await step(admin, 'P03 Google / Microsoft sign-in when not configured says so', async () => {
    const p = await newRolePage(browser);
    await p.goto(`${BASE}/login/oidc/google`);
    expect(new URL(p.url()).pathname === '/login', `went to ${p.url()}`);
    const f = await flash(p);
    expect(/not set up/i.test(f.err), `no clear error: ${JSON.stringify(f)}`);
    await p.context().close();
  });

  // ------------------------------------------------ two-step login
  await step(pages.doctor, 'P04 doctor turns on two-step login and gets 10 recovery codes', async () => {
    const p = pages.doctor;
    await p.goto(`${BASE}/account/2fa`);
    await p.getByRole('button', { name: 'Start set-up' }).click();
    await p.waitForLoadState('domcontentloaded');
    const secret = one("SELECT totp_secret FROM users WHERE username='doctor'").totp_secret;
    expect(secret && (await text(p)).replace(/\s/g, '').includes(secret), 'secret not shown for manual entry');
    await p.getByLabel('Code', { exact: true }).fill('000000');
    await p.getByRole('button', { name: 'Turn on two-step login' }).click();
    await p.waitForLoadState('domcontentloaded');
    expect(/didn't match/i.test((await flash(p)).err), 'wrong enrolment code was not refused');
    expect(one("SELECT totp_enabled FROM users WHERE username='doctor'").totp_enabled === 0, '2FA turned on with a wrong code');
    await p.getByLabel('Code', { exact: true }).fill(freshCode('doctor').code);
    await p.getByRole('button', { name: 'Turn on two-step login' }).click();
    await p.waitForLoadState('domcontentloaded');
    const codes = (await p.getByLabel('Recovery codes').innerText()).match(/[0-9a-f]{6}-[0-9a-f]{6}/g) || [];
    expect(codes.length === 10, `${codes.length} recovery codes shown`);
    expect(one("SELECT COUNT(*) n FROM user_recovery_codes WHERE user_id=(SELECT id FROM users WHERE username='doctor') AND used_at IS NULL").n === 10, 'codes not stored');
    st.recovery = codes;
  });

  await step(admin, 'P05 2FA login: wrong code 401, right code in, same code cannot be replayed', async () => {
    const p = await newRolePage(browser);
    await p.goto(`${BASE}/login`);
    await p.getByLabel('Username').fill('doctor');
    await p.getByLabel('Password').fill(PASSWORD);
    await p.getByRole('button', { name: 'Log in' }).click();
    await p.waitForLoadState('domcontentloaded');
    expect(new URL(p.url()).pathname === '/login/2fa', `no second step: ${p.url()}`);
    const r404 = await p.goto(`${BASE}/appointments`);
    expect(new URL(p.url()).pathname === '/login', `password alone opened ${p.url()} (${r404.status()})`);
    await p.goBack();
    await p.goto(`${BASE}/login/2fa`);
    const wrong = await Promise.all([p.waitForResponse(r => r.url().endsWith('/login/2fa') && r.request().method() === 'POST'),
      (async () => { await p.getByLabel(/6-digit code/i).fill('123456'); await p.getByRole('button', { name: 'Continue' }).click(); })()]);
    expect(wrong[0].status() === 401, `wrong code answered ${wrong[0].status()}`);
    expect(/didn't work/i.test(await text(p)), 'no error text for a wrong code');
    const c = freshCode('doctor');
    await p.getByLabel(/6-digit code/i).fill(c.code);
    await p.getByRole('button', { name: 'Continue' }).click();
    await p.waitForLoadState('domcontentloaded');
    expect(new URL(p.url()).pathname === '/appointments', `right code landed on ${p.url()}`);
    // Replay the same code in a second browser.
    const q = await newRolePage(browser);
    await q.goto(`${BASE}/login`);
    await q.getByLabel('Username').fill('doctor');
    await q.getByLabel('Password').fill(PASSWORD);
    await q.getByRole('button', { name: 'Log in' }).click();
    await q.waitForLoadState('domcontentloaded');
    await q.getByLabel(/6-digit code/i).fill(c.code);
    await q.getByRole('button', { name: 'Continue' }).click();
    await q.waitForLoadState('domcontentloaded');
    expect(new URL(q.url()).pathname === '/login/2fa', `replayed code was accepted: ${q.url()}`);
    st.doctorQ = q;   // still waiting at the second step, used by P06
    await p.context().close();
  });

  await step(admin, 'P06 recovery code logs in once, then is spent', async () => {
    const q = st.doctorQ;
    expect(q && st.recovery, 'needs P04 and P05');
    await q.getByLabel(/6-digit code/i).fill(st.recovery[0]);
    await q.getByRole('button', { name: 'Continue' }).click();
    await q.waitForLoadState('domcontentloaded');
    expect(new URL(q.url()).pathname === '/appointments', `recovery code did not log in: ${q.url()}`);
    const r = await newRolePage(browser);
    await r.goto(`${BASE}/login`);
    await r.getByLabel('Username').fill('doctor');
    await r.getByLabel('Password').fill(PASSWORD);
    await r.getByRole('button', { name: 'Log in' }).click();
    await r.waitForLoadState('domcontentloaded');
    await r.getByLabel(/6-digit code/i).fill(st.recovery[0]);
    await r.getByRole('button', { name: 'Continue' }).click();
    await r.waitForLoadState('domcontentloaded');
    expect(new URL(r.url()).pathname === '/login/2fa', 'a used recovery code worked twice');
    await r.context().close();
    await q.context().close();
  });

  await step(admin, 'P07 admin requires 2FA for nurses: nurse is held at set-up until done, then policy cleared', async () => {
    await admin.goto(`${BASE}/account`);
    await admin.getByLabel('Nurse', { exact: true }).check();
    await admin.getByRole('button', { name: 'Save policy' }).click();
    await admin.waitForLoadState('domcontentloaded');
    expect(/required for: Nurse/i.test((await flash(admin)).msg), 'policy not confirmed');
    const n = await newRolePage(browser);
    await login(n, 'nurse');
    await n.goto(`${BASE}/vitals`);
    expect(new URL(n.url()).pathname === '/account/2fa', `nurse without 2FA opened ${n.url()}`);
    expect(/needs two-step login/i.test((await flash(n)).err), 'no explanation for the nurse');
    await admin.goto(`${BASE}/account`);
    await admin.getByLabel('Nurse', { exact: true }).uncheck();
    await admin.getByRole('button', { name: 'Save policy' }).click();
    await admin.waitForLoadState('domcontentloaded');
    const r = await n.goto(`${BASE}/vitals`);
    expect(r.status() === 200 && new URL(n.url()).pathname === '/vitals', `nurse still blocked after the policy was cleared: ${n.url()}`);
    await n.context().close();
  });

  await step(admin, 'P08 idle timeout: a session idle for 16 min is refused, 1 min is fine', async () => {
    const mk = mins => py([
      'import json, time, secrets', 'from app import auth, db',
      'u = db.one("SELECT id, session_version FROM users WHERE username = \'billing\'")',
      `now = int(time.time()); t = now - ${mins} * 60`,
      'print(json.dumps(auth._serializer().dumps({"u": u["id"], "v": u["session_version"], "c": secrets.token_urlsafe(24), "i": t - 60, "t": t})))',
    ].join('\n'));
    const out = {};
    for (const mins of [16, 1]) {
      const ctx = await browser.newContext();
      await ctx.addCookies([{ name: 'tt_session', value: mk(mins), url: BASE }]);
      const p = await ctx.newPage();
      await p.goto(`${BASE}/billing`);
      out[mins] = new URL(p.url()).pathname;
      await ctx.close();
    }
    expect(out[16] === '/login', `16-minute idle session opened ${out[16]}`);
    expect(out[1] === '/billing', `1-minute idle session was refused (${out[1]})`);
  });

  await step(admin, 'P09 "Sign out on every other device" ends the other session only', async () => {
    const a = await newRolePage(browser);
    const b = await newRolePage(browser);
    await login(a, 'billing');
    await login(b, 'billing');
    await b.goto(`${BASE}/account`);
    await b.getByRole('button', { name: 'Sign out on every other device' }).click();
    await b.waitForLoadState('domcontentloaded');
    await a.goto(`${BASE}/billing`);
    expect(new URL(a.url()).pathname === '/login', `other device still signed in: ${a.url()}`);
    await b.goto(`${BASE}/billing`);
    expect(new URL(b.url()).pathname === '/billing', 'this device was signed out too');
    await a.context().close(); await b.context().close();
    // pages.billing was the "other device"; log it in again.
    await login(pages.billing, 'billing');
  });

  await step(admin, 'P10 wrong current password on My account is refused', async () => {
    const p = pages.billing;
    await p.goto(`${BASE}/account`);
    await p.getByLabel('Current password').fill('not-my-password');
    await p.getByLabel(/^New password/).fill('Another@123');
    await p.getByLabel('Type it again').fill('Another@123');
    await p.getByRole('button', { name: 'Change password' }).click();
    await p.waitForLoadState('domcontentloaded');
    expect(/current password is not right/i.test((await flash(p)).err), 'no error');
    await p.goto(`${BASE}/billing`);
    expect(new URL(p.url()).pathname === '/billing', 'session lost after a failed change');
  });

  // ------------------------------------------------ Diagnostics: lab
  const lab = pages.lab;
  const P1 = { name: `QA Lab One ${RUN}`, phone: phoneFor(1) };
  const P2 = { name: `QA Crit Two ${RUN}`, phone: phoneFor(2) };
  const P3 = { name: `QA Range Three ${RUN}`, phone: phoneFor(3) };

  async function orderTest(page, p, testName) {
    await page.goto(`${BASE}/diagnostics?tab=lab`);
    await page.getByRole('button', { name: 'Order a test' }).click();
    const dlg = page.getByRole('dialog', { name: 'Order a test' });
    await dlg.getByLabel('Patient name').fill(p.name);
    await dlg.getByLabel('Mobile number').fill(p.phone);
    await dlg.getByLabel('Test').selectOption(one('SELECT code FROM lab_tests WHERE name = ?', [testName]).code);
    await dlg.getByRole('button', { name: 'Order test' }).click();
    await page.waitForLoadState('domcontentloaded');
    const f = await flash(page);
    expect(/Test ordered/.test(f.msg), `order not confirmed: ${JSON.stringify(f)}`);
    return one("SELECT l.* FROM lab_orders l JOIN patients p ON p.id=l.patient_id JOIN lab_tests t ON t.code=l.test_code" +
      ' WHERE p.phone=? AND t.name=? ORDER BY l.id DESC LIMIT 1', ['91' + p.phone, testName]);
  }
  const labRow = (page, p, testName) => page.getByRole('row').filter({ hasText: p.name }).filter({ hasText: testName });
  async function collectReceive(page, p, testName) {
    await labRow(page, p, testName).getByRole('button', { name: /^Collect/ }).click();
    await page.waitForLoadState('domcontentloaded');
    await labRow(page, p, testName).getByRole('button', { name: /^Receive/ }).click();
    await page.waitForLoadState('domcontentloaded');
  }
  async function enterResult(page, p, testName, value) {
    await labRow(page, p, testName).getByLabel(new RegExp('^Result for ' + testName)).fill(String(value));
    await labRow(page, p, testName).getByRole('button', { name: /^Advance/ }).click();
    await page.waitForLoadState('domcontentloaded');
    return flash(page);
  }

  await step(lab, 'P11 lab: order -> collect (sample ID) -> receive -> normal result auto-verified', async () => {
    const o = await orderTest(lab, P1, 'Serum potassium');
    expect(o && o.status === 'Ordered' && o.branch_id === 'A', `order row: ${JSON.stringify(o)}`);
    const ord = one('SELECT amount, bill_id FROM orders WHERE id=?', [o.order_id]);
    expect(ord.amount === 250 && ord.bill_id === null, `service order ${JSON.stringify(ord)} (expected ₹250, unbilled)`);
    await collectReceive(lab, P1, 'Serum potassium');
    const mid = one('SELECT status, sample_id FROM lab_orders WHERE id=?', [o.id]);
    expect(mid.status === 'Received' && /^A-L\d{6}-\d{5}$/.test(mid.sample_id || ''), `after collect+receive: ${JSON.stringify(mid)}`);
    expect((await labRow(lab, P1, 'Serum potassium').innerText()).includes(mid.sample_id), 'sample ID not shown on the row');
    const f = await enterResult(lab, P1, 'Serum potassium', '4.2');
    expect(/auto-verified/i.test(f.msg), `toast: ${JSON.stringify(f)}`);
    const done = one('SELECT status, flag, validated_by, auto_validated FROM lab_orders WHERE id=?', [o.id]);
    expect(done.status === 'Validated' && done.flag === 'N' && done.validated_by === 'auto-verify', JSON.stringify(done));
    st.p1k = o;
  });

  await step(lab, 'P12 critical K 6.8: no Validate button, server refuses validation, call-out needs read-back', async () => {
    const o = await orderTest(lab, P2, 'Serum potassium');
    await collectReceive(lab, P2, 'Serum potassium');
    const f = await enterResult(lab, P2, 'Serum potassium', '6.8');
    expect(/Critical value/i.test(f.msg), `toast: ${JSON.stringify(f)}`);
    const r = one('SELECT l.status, l.flag, c.status AS cs FROM lab_orders l JOIN lab_callouts c ON c.lab_order_id=l.id WHERE l.id=?', [o.id]);
    expect(r && r.status === 'Resulted' && r.flag === 'HH' && r.cs === 'Open', `after result: ${JSON.stringify(r)}`);
    const row = labRow(lab, P2, 'Serum potassium');
    expect(await row.getByRole('button', { name: /Validate/ }).count() === 0, 'Validate shown before the call-out');
    expect(await row.getByLabel('critical', { exact: true }).count() === 1, 'critical marker has no accessible label');
    const v = await post(lab, `/diagnostics/lab/${o.id}/validate`);
    expect(/Call out this critical value/i.test(v.body), `validate before call-out was not refused (HTTP ${v.status})`);
    expect(one('SELECT status FROM lab_orders WHERE id=?', [o.id]).status === 'Resulted', 'critical validated before call-out');
    const nb = await post(lab, `/diagnostics/lab/${o.id}/callout`, { called_to: 'Dr Test, ward 3' });
    expect(/read the value back/i.test(nb.body), 'call-out without read-back was not refused');
    expect(one('SELECT status FROM lab_callouts WHERE lab_order_id=?', [o.id]).status === 'Open', 'call-out recorded without read-back');
    // Task for the call-out exists and is due in 15 minutes.
    const t = one("SELECT status, (julianday(due_at)-julianday(created_at))*1440 AS mins FROM tasks WHERE related_type='lab_order' AND related_id=?", [o.id]);
    expect(t && t.status === 'Open' && Math.round(t.mins) === 15, `urgent task: ${JSON.stringify(t)}`);
    st.p2k = o;
  });

  await step(pages.doctor, 'P13 doctor bell shows the critical value; opening it goes to the lab row and marks it read', async () => {
    const d = await newRolePage(browser);
    await login(d, 'doctor');
    pages.doctor = d;
    const uid = one("SELECT id FROM users WHERE username='doctor'").id;
    const n = one("SELECT id FROM notifications WHERE user_id=? AND title LIKE 'Critical value:%' AND title LIKE ? AND read_at IS NULL", [uid, `%${P2.name}%`]);
    expect(n, 'no critical notification for the branch doctor');
    await d.goto(`${BASE}/appointments`);
    const summary = d.locator('summary[aria-label^="Notifications"]');
    const label = await summary.getAttribute('aria-label');
    expect(/\d+ unread/.test(label), `bell label "${label}"`);
    await summary.click();
    await d.getByRole('button', { name: new RegExp(`Critical value: Serum potassium 6\\.8.*${P2.name}`) }).click();
    await d.waitForLoadState('domcontentloaded');
    expect(new URL(d.url()).pathname === '/diagnostics' && d.url().includes(`#lab-${st.p2k.id}`), `went to ${d.url()}`);
    expect(one('SELECT read_at FROM notifications WHERE id=?', [n.id]).read_at, 'not marked read');
    // Someone else's notification is a 404.
    const other = one('SELECT id FROM notifications WHERE user_id<>? ORDER BY id LIMIT 1', [uid]);
    const r = await post(d, `/notifications/${other.id}/open`);
    expect(r.status === 404, `other user's notification answered ${r.status}`);
    await d.goto(`${BASE}/notifications`);
    const markAll = d.getByRole('button', { name: /Mark all as read/ });
    if (await markAll.count()) { await markAll.click(); await d.waitForLoadState('domcontentloaded'); }
    expect(one('SELECT COUNT(*) n FROM notifications WHERE user_id=? AND read_at IS NULL', [uid]).n === 0, 'unread left after Mark all');
  });

  await step(lab, 'P14 lab records the call-out with read-back, then validates', async () => {
    const row = labRow(lab, P2, 'Serum potassium');
    await lab.goto(`${BASE}/diagnostics?tab=lab`);
    await row.getByRole('button', { name: /Call out/ }).click();
    const dlg = lab.getByRole('dialog', { name: 'Critical value call-out' });
    await dlg.getByLabel(/Who received the call/).fill('Dr Menon, ward 3 duty doctor');
    await dlg.getByLabel(/read the value back/).check();
    await dlg.getByRole('button', { name: 'Record call-out' }).click();
    await lab.waitForLoadState('domcontentloaded');
    const c = one('SELECT status, read_back, called_to FROM lab_callouts WHERE lab_order_id=?', [st.p2k.id]);
    expect(c.status === 'CalledOut' && c.read_back === 1, JSON.stringify(c));
    expect(one("SELECT status FROM tasks WHERE related_type='lab_order' AND related_id=?", [st.p2k.id]).status === 'Done', 'urgent task left open');
    await labRow(lab, P2, 'Serum potassium').getByRole('button', { name: /Validate/ }).click();
    await lab.waitForLoadState('domcontentloaded');
    expect(one('SELECT status FROM lab_orders WHERE id=?', [st.p2k.id]).status === 'Validated', 'not validated');
  });

  await step(admin, 'P15 critical value not called out in 15 min escalates to admin and owner (time travel +40 min)', async () => {
    const open = one("SELECT COUNT(*) n FROM lab_callouts WHERE status='Open' AND escalated_at IS NULL").n;
    if (!open) return 'SKIP no open call-out in the seed';
    const n = py(['import json', 'from datetime import timedelta', 'from app import diagnostics, util',
      'print(json.dumps(diagnostics.escalate_callouts(util.now() + timedelta(minutes=40))))'].join('\n'));
    expect(n >= 1, `${n} escalated`);
    const again = py(['import json', 'from datetime import timedelta', 'from app import diagnostics, util',
      'print(json.dumps(diagnostics.escalate_callouts(util.now() + timedelta(minutes=41))))'].join('\n'));
    expect(again === 0, `escalated again on the next sweep (${again})`);
    await pages.owner.goto(`${BASE}/notifications`);
    expect(/Not called out in 15 min/.test(await text(pages.owner)), 'owner has no escalation notification');
    return `${n} escalated, idempotent`;
  });

  await step(lab, 'P16 reflex rule: TSH 8.4 (high) adds Free T4 automatically and waits for a pathologist', async () => {
    const o = await orderTest(lab, P1, 'TSH');
    await collectReceive(lab, P1, 'TSH');
    const f = await enterResult(lab, P1, 'TSH', '8.4');
    expect(/Reflex test added/i.test(f.msg), `toast: ${JSON.stringify(f)}`);
    const kid = one('SELECT test_code, status FROM lab_orders WHERE reflex_of=?', [o.id]);
    expect(kid && kid.test_code === 'FT4' && kid.status === 'Received', `reflex child ${JSON.stringify(kid)}`);
    expect(one('SELECT status FROM lab_orders WHERE id=?', [o.id]).status === 'Resulted', 'high TSH auto-verified');
    const tshRow = lab.getByRole('row').filter({ hasText: P1.name }).filter({ hasText: 'TSH' }).filter({ hasNotText: 'Reflex test after' });
    expect(/Free T4 added automatically \(reflex rule\)/.test(await tshRow.innerText()), 'reflex note not shown');
    st.p1tsh = o;
  });

  await step(lab, 'P17 reference range: adult of unknown age/sex is not judged on a child range', async () => {
    // The order dialog does not ask for age or sex. HCT 37 % is low for an adult man (40-50) and inside
    // the child range (35-41). It must wait for a pathologist, not be auto-verified as normal.
    const o = await orderTest(lab, P3, 'Haematocrit');
    await collectReceive(lab, P3, 'Haematocrit');
    await enterResult(lab, P3, 'Haematocrit', '37');
    const r = one('SELECT status, flag, ref_low, ref_high, validated_by FROM lab_orders WHERE id=?', [o.id]);
    expect(!(r.status === 'Validated' && r.ref_low === 35 && r.ref_high === 41),
      `auto-verified as normal against the paediatric range ${r.ref_low}-${r.ref_high} (flag ${r.flag}, by ${r.validated_by})`);
  });

  await step(lab, 'P18 negative: other-branch lab order is 404 and unchanged; pharmacy cannot enter results', async () => {
    const b = one("SELECT id, status FROM lab_orders WHERE branch_id='B' AND status IN ('Ordered','Collected') ORDER BY id LIMIT 1");
    await lab.goto(`${BASE}/diagnostics?tab=lab`);
    const r = await post(lab, `/diagnostics/lab/${b.id}/advance`);
    expect(r.status === 404, `branch-B order answered ${r.status} for a branch-A lab user`);
    expect(one('SELECT status FROM lab_orders WHERE id=?', [b.id]).status === b.status, 'branch-B order changed');
    const ph = pages.pharmacy;
    await ph.goto(`${BASE}/account`);
    const a = one("SELECT id FROM lab_orders WHERE branch_id='A' AND status='Received' ORDER BY id LIMIT 1");
    const r2 = await post(ph, `/diagnostics/lab/${a.id}/result`, { value: '4.0' });
    expect(r2.status === 403, `pharmacy result entry answered ${r2.status}`);
  });

  await step(admin, 'P19 negative: front desk cannot enter a lab result (clinical data entry)', async () => {
    const fb = pages.frontb;
    const o = one("SELECT id, status FROM lab_orders WHERE branch_id='B' AND status='Collected' ORDER BY id LIMIT 1") ||
      one("SELECT id, status FROM lab_orders WHERE branch_id='B' AND status='Ordered' ORDER BY id LIMIT 1");
    if (!o) return 'SKIP no branch-B order to try';
    await fb.goto(`${BASE}/diagnostics?tab=lab`);
    const r = await post(fb, `/diagnostics/lab/${o.id}/advance`);
    const after = one('SELECT status FROM lab_orders WHERE id=?', [o.id]).status;
    expect(r.status === 403 && after === o.status, `front desk moved lab order ${o.id} from ${o.status} to ${after} (HTTP ${r.status}); LAB_ROLES lets front desk collect, receive and enter results`);
  });

  // ------------------------------------------------ Diagnostics: radiology
  await step(admin, 'P20 radiology: obstetric USG cannot be performed without Form F; obstetric X-ray refused', async () => {
    const rad = one("SELECT r.id, p.name FROM rad_orders r JOIN patients p ON p.id=r.patient_id WHERE r.is_obstetric=1 AND r.status='Scheduled' LIMIT 1");
    expect(rad, 'no obstetric scan in the seed');
    await admin.goto(`${BASE}/diagnostics?tab=rad`);
    const r = await post(admin, `/diagnostics/rad/${rad.id}/advance`);
    expect(/PCPNDT/.test(r.body), 'performed without Form F was not refused');
    expect(one('SELECT status FROM rad_orders WHERE id=?', [rad.id]).status === 'Scheduled', 'scan moved on without Form F');
    const row = admin.getByRole('row').filter({ hasText: rad.name }).filter({ hasText: 'Obstetric' });
    await row.getByLabel('Form F completed').check();
    await row.getByRole('button', { name: /Performed/ }).click();
    await admin.waitForLoadState('domcontentloaded');
    const after = one('SELECT status, form_f_recorded FROM rad_orders WHERE id=?', [rad.id]);
    expect(after.status === 'Performed' && after.form_f_recorded === 1, JSON.stringify(after));
    const x = await post(admin, '/diagnostics/rad/order', { name: `QA Xray ${RUN}`, phone: phoneFor(4), modality: 'X-ray',
      study: 'Abdomen', slot_at: '2026-12-01T10:00', obstetric: '1', branch_id: 'A' });
    expect(/Only ultrasound/.test(x.body), 'obstetric X-ray accepted');
    expect(!/sex|gender/i.test(await admin.getByRole('dialog', { name: 'Schedule a scan' }).innerText().catch(() => '')), 'scan form asks for sex');
  });

  await step(admin, 'P21 radiology roles: "Lab / radiology" staff can perform a scan; front desk cannot write a report', async () => {
    const bad = [];
    await lab.goto(`${BASE}/diagnostics?tab=rad`);
    const labCan = await lab.getByRole('button', { name: /Performed|Write report/ }).count();
    if (!labCan) bad.push('lab (Lab / radiology) role sees no radiology actions');
    const perf = one("SELECT id, status FROM rad_orders WHERE branch_id='B' AND status='Performed' LIMIT 1");
    if (perf) {
      await pages.frontb.goto(`${BASE}/diagnostics?tab=rad`);
      const r = await post(pages.frontb, `/diagnostics/rad/${perf.id}/advance`, { report_text: 'QA: front desk wrote this report' });
      const now = one('SELECT status, reported_by FROM rad_orders WHERE id=?', [perf.id]);
      if (now.status === 'Reported') bad.push(`front desk signed the radiology report on scan ${perf.id} (reported_by ${now.reported_by}, HTTP ${r.status})`);
    }
    expect(!bad.length, bad.join('; '));
  });

  // ------------------------------------------------ Pharmacy
  await step(pages.pharmacy, 'P22 pharmacy role can open the Pharmacy counter', async () => {
    const r = await pages.pharmacy.goto(`${BASE}/diagnostics?tab=rx`);
    expect(r.status() === 200, `pharmacy role gets HTTP ${r.status()} on /diagnostics?tab=rx (RX_ROLES names "pharmacist")`);
  });

  await step(admin, 'P23 dispense FEFO + Schedule H register, then bill: total = sum of items', async () => {
    const rx = one("SELECT x.id, p.name FROM prescriptions x JOIN patients p ON p.id=x.patient_id WHERE x.status='Pending' AND x.branch_id='A' LIMIT 1");
    const items = sql('SELECT i.id, i.drug_code, i.qty, g.schedule, g.unit_price FROM prescription_items i JOIN drugs g ON g.code=i.drug_code WHERE prescription_id=?', [rx.id]);
    const before = {};
    const today = new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
    for (const it of items) {
      before[it.id] = one('SELECT id, qty FROM drug_batches WHERE drug_code=? AND branch_id=\'A\' AND qty>=? AND expiry>? ORDER BY expiry, id LIMIT 1', [it.drug_code, it.qty, today]);
    }
    const regBefore = one('SELECT COUNT(*) n FROM schedule_register').n;
    await admin.goto(`${BASE}/diagnostics?tab=rx`);
    const rxItem = name => admin.getByRole('listitem').filter({ hasText: rx.name }).filter({ has: admin.getByRole('button', { name }) });
    await rxItem(/Dispense/).getByRole('button', { name: /Dispense/ }).click();
    await admin.waitForLoadState('domcontentloaded');
    for (const it of items) {
      const got = one('SELECT batch_id, amount FROM prescription_items WHERE id=?', [it.id]);
      expect(got.batch_id === before[it.id].id, `${it.drug_code}: batch ${got.batch_id}, FEFO batch is ${before[it.id].id}`);
      expect(one('SELECT qty FROM drug_batches WHERE id=?', [got.batch_id]).qty === before[it.id].qty - it.qty, `${it.drug_code} stock not reduced by ${it.qty}`);
    }
    const scheduled = items.filter(i => i.schedule).length;
    expect(one('SELECT COUNT(*) n FROM schedule_register').n - regBefore === scheduled, `register rows added != ${scheduled} scheduled drugs`);
    await rxItem(/Create bill/).getByRole('button', { name: /Create bill/ }).click();
    await admin.waitForLoadState('domcontentloaded');
    const x = one('SELECT status, bill_id FROM prescriptions WHERE id=?', [rx.id]);
    const bill = one('SELECT total, (SELECT SUM(amount) FROM bill_items WHERE bill_id=bills.id) AS items FROM bills WHERE id=?', [x.bill_id]);
    const expected = items.reduce((s, i) => s + i.qty * i.unit_price, 0);
    expect(x.status === 'Billed' && bill.total === expected && bill.items === expected, `bill ${JSON.stringify(bill)}, expected ₹${expected}`);
    return `₹${expected}, ${scheduled} register row(s)`;
  });

  await step(admin, 'P24 idempotency: a double-clicked "Dispense" does not also create the bill', async () => {
    const rx = one("SELECT id FROM prescriptions WHERE status='Pending' LIMIT 1");
    if (!rx) return 'SKIP no pending prescription';
    await admin.goto(`${BASE}/diagnostics?tab=rx`);
    await Promise.all([post(admin, `/diagnostics/rx/${rx.id}/advance`), post(admin, `/diagnostics/rx/${rx.id}/advance`)]);
    const s = one('SELECT status, bill_id FROM prescriptions WHERE id=?', [rx.id]);
    expect(s.status === 'Dispensed', `two clicks on Dispense left prescription ${rx.id} as ${s.status} (bill ${s.bill_id})`);
  });

  // ------------------------------------------------ Command Centre
  await step(pages.doctor, 'P25 Command Centre: doctor sees own branch, numbers match the database, wall mode loads', async () => {
    const d = pages.doctor;
    const r = await d.goto(`${BASE}/command`);
    expect(r.status() === 200, `HTTP ${r.status()}`);
    const t = await text(d);
    const bName = one("SELECT name FROM branches WHERE id='A'").name;
    const oName = one("SELECT name FROM branches WHERE id='B'").name;
    expect(t.includes(bName), 'own branch missing');
    expect(!t.includes(oName), 'branch-bound doctor sees the other branch');
    const w = await d.goto(`${BASE}/command?wall=1`);
    expect(w.status() === 200, `wall mode HTTP ${w.status()}`);
    const nr = await pages.nurse.goto(`${BASE}/command`);
    expect(nr.status() === 403, `nurse got ${nr.status()}`);
    const occ = one("SELECT SUM(bd.status='Occupied') o, COUNT(*) n FROM beds bd JOIN wards w ON w.id=bd.ward_id WHERE w.branch_id='A'");
    const pct = Math.round(100 * occ.o / occ.n);
    await d.goto(`${BASE}/command`);
    expect(await d.getByRole('img', { name: `${pct} percent occupied` }).count() === 1, `bed occupancy ${pct}% not shown`);
    expect(new RegExp(`${occ.o}\\s*/${occ.n}`).test(await text(d)), `beds ${occ.o}/${occ.n} not shown`);
    return `branch A occupancy ${pct}%`;
  });

  // ------------------------------------------------ AI Labs
  await step(admin, 'P26 AI Labs: owner sees findings but cannot decide; admin runs agents', async () => {
    await admin.goto(`${BASE}/ai-labs`);
    for (const title of ['Revenue-loss finder', 'No-show risk', 'Stock and expiry']) {
      await admin.getByRole('article').filter({ hasText: title }).getByRole('button', { name: 'Check now' }).click();
      await admin.waitForLoadState('domcontentloaded');
      await admin.goto(`${BASE}/ai-labs`);
    }
    const n = one("SELECT COUNT(*) n FROM findings WHERE status='open'").n;
    expect(n > 0, 'agents found nothing on the demo seed');
    expect(one("SELECT COUNT(*) n FROM findings WHERE status<>'open'").n === 0, 'a finding was decided without a person');
    const o = pages.owner;
    await o.goto(`${BASE}/ai-labs`);
    expect(await o.getByRole('button', { name: 'Accept' }).count() === 0, 'owner sees Accept');
    expect(/An admin decides findings/.test(await text(o)), 'owner gets no explanation');
    const f = one("SELECT id FROM findings WHERE status='open' LIMIT 1");
    const r = await post(o, `/ai-labs/findings/${f.id}/accept`);
    expect(r.status === 403, `owner accept answered ${r.status}`);
    return `${n} open findings`;
  });

  await step(admin, 'P27 AI Labs: nothing happens until Accept; Accept runs the action once; Dismiss needs a reason', async () => {
    const f = one("SELECT id, title, action FROM findings WHERE status='open' AND action LIKE '%add_order_to_bill%' LIMIT 1");
    if (!f) return 'SKIP no revenue finding';
    const orderId = JSON.parse(f.action).order_id;
    expect(one('SELECT bill_id FROM orders WHERE id=?', [orderId]).bill_id === null, 'order billed before anyone accepted');
    await admin.goto(`${BASE}/ai-labs?agent=revenue_loss`);
    await admin.getByRole('listitem').filter({ hasText: f.title }).getByRole('button', { name: 'Accept' }).click();
    await admin.waitForLoadState('domcontentloaded');
    expect(/Added to bill/.test((await flash(admin)).msg), 'no confirmation');
    const ord = one('SELECT bill_id FROM orders WHERE id=?', [orderId]);
    const bill = one('SELECT total, (SELECT SUM(amount) FROM bill_items WHERE bill_id=bills.id) s FROM bills WHERE id=?', [ord.bill_id]);
    expect(ord.bill_id && bill.total === bill.s, `bill ${JSON.stringify(bill)}`);
    expect(one('SELECT status, decided_by FROM findings WHERE id=?', [f.id]).decided_by === 'user:admin', 'decision not attributed');
    const again = await post(admin, `/ai-labs/findings/${f.id}/accept`);
    expect(/already decided/.test(again.body), 'second accept not refused');
    const g = one("SELECT id, title FROM findings WHERE status='open' LIMIT 1");
    const nr = await post(admin, `/ai-labs/findings/${g.id}/dismiss`, { note: '' });
    expect(/Say briefly why/.test(nr.body), 'dismiss without a reason accepted');
    await admin.goto(`${BASE}/ai-labs`);
    const li = admin.getByRole('listitem').filter({ hasText: g.title }).first();
    await li.getByLabel('Reason').fill('QA: not relevant for this demo');
    await li.getByRole('button', { name: 'Dismiss' }).click();
    await admin.waitForLoadState('domcontentloaded');
    const d = one('SELECT status, decision_note FROM findings WHERE id=?', [g.id]);
    expect(d.status === 'dismissed' && /QA/.test(d.decision_note), JSON.stringify(d));
  });

  // ------------------------------------------------ AI features
  await step(pages.frontb, 'P28 no-show risk pill on Appointments with reasons, labelled decision support', async () => {
    const fb = pages.frontb;
    let found = null;
    for (let i = 0; i < 4 && !found; i++) {
      const d = new Date(Date.now() + 5.5 * 3600e3 + i * 864e5).toISOString().slice(0, 10);
      await fb.goto(`${BASE}/appointments?day=${d}`);
      const pill = fb.getByText(/no-show risk$/);
      if (await pill.count()) found = { d, label: await fb.getByLabel(/^No-show risk (high|medium)/).first().getAttribute('aria-label'), title: await fb.getByText(/no-show risk$/).first().getAttribute('title') };
    }
    expect(found, 'no risk pill on the next 4 days');
    expect(/Reasons: .+/.test(found.label), `no reasons: ${found.label}`);
    expect(/decision support/i.test(found.title), 'not labelled decision support');
    return `${found.d}: ${found.label.slice(0, 60)}`;
  });

  await step(pages.frontb, 'P29 draft reply fills the box, sends nothing, and is logged as a suggestion', async () => {
    const fb = pages.frontb;
    // A fresh seed has almost no WhatsApp history: a branch-B patient writes in first (simulator).
    const bp = one("SELECT p.phone, p.name FROM patients p JOIN appointments a ON a.patient_id=p.id WHERE a.branch_id='B' AND p.id NOT IN (SELECT patient_id FROM appointments WHERE branch_id='A') LIMIT 1");
    await fb.goto(`${BASE}/messages`);
    await simulate(fb, bp.phone.slice(2), 'Can I come at 5 pm instead?');
    await fb.goto(`${BASE}/messages?phone=${bp.phone}`);
    expect((await text(fb)).includes(bp.name), 'branch-B conversation not listed for branch-B front desk');
    const sent = one('SELECT COUNT(*) n FROM messages').n;
    const sugg = one("SELECT COUNT(*) n FROM ai_decisions WHERE feature='draft_reply' AND decision='suggested'").n;
    await fb.getByRole('button', { name: 'Draft reply' }).click();
    await fb.waitForLoadState('domcontentloaded');
    const val = await fb.getByPlaceholder('Write a reply…').inputValue();
    expect(val.trim().length > 5, 'reply box is empty');
    expect(/Nothing is sent until you press Send/.test(await text(fb)), 'no human-review note');
    expect(one('SELECT COUNT(*) n FROM messages').n === sent, 'a message was sent by Draft reply');
    expect(one("SELECT COUNT(*) n FROM ai_decisions WHERE feature='draft_reply' AND decision='suggested'").n === sugg + 1, 'suggestion not logged');
    // Draft for a conversation outside branch B is a 404.
    const ap = one("SELECT p.phone FROM patients p JOIN appointments a ON a.patient_id=p.id WHERE a.branch_id='A' AND p.id NOT IN (" +
      "SELECT patient_id FROM appointments WHERE branch_id='B' UNION SELECT patient_id FROM bills WHERE branch_id='B' UNION SELECT patient_id FROM orders WHERE branch_id='B'" +
      " UNION SELECT patient_id FROM claims WHERE branch_id='B' UNION SELECT patient_id FROM followups WHERE branch_id='B') LIMIT 1");
    await admin.goto(`${BASE}/messages`);
    await simulate(admin, ap.phone.slice(2), 'What are the OPD timings?');
    {
      const r = await post(fb, '/messages/draft', { phone: ap.phone });
      expect(r.status === 404, `branch-A conversation draft answered ${r.status}`);
    }
  });

  await step(pages.billing, 'P30 coding assistant: suggestions need a coder; edited codes saved; owner and other branch refused', async () => {
    const b = pages.billing;
    await b.goto(`${BASE}/claims`);
    let s = one("SELECT s.id, s.claim_id, s.suggestions, p.name FROM coding_suggestions s JOIN claims c ON c.id=s.claim_id JOIN patients p ON p.id=c.patient_id WHERE s.status='Proposed' AND c.branch_id='A' LIMIT 1");
    if (!s) {
      for (const c of sql("SELECT id FROM claims WHERE branch_id='A' AND id NOT IN (SELECT claim_id FROM coding_suggestions) LIMIT 6")) {
        await post(b, `/claims/${c.id}/codes/suggest`);
        s = one("SELECT s.id, s.claim_id, s.suggestions, p.name FROM coding_suggestions s JOIN claims c ON c.id=s.claim_id JOIN patients p ON p.id=c.patient_id WHERE s.status='Proposed' AND c.branch_id='A' AND json_array_length(s.suggestions)>0 LIMIT 1");
        if (s) break;
      }
    }
    expect(s, 'no code suggestion could be made for a branch-A claim');
    const stage = one('SELECT stage FROM claims WHERE id=?', [s.claim_id]).stage;
    await b.goto(`${BASE}/claims`);
    const field = b.getByLabel(`Codes to keep for ${s.name}`);
    const proposed = await field.inputValue();
    await field.fill(proposed.split(',')[0].trim());
    await b.locator('form').filter({ has: field }).getByRole('button', { name: 'Save codes' }).click();
    await b.waitForLoadState('domcontentloaded');
    const after = one('SELECT status, accepted_codes, decided_by FROM coding_suggestions WHERE id=?', [s.id]);
    expect(after.status === 'Accepted' && after.decided_by === 'user:billing', JSON.stringify(after));
    const dec = one("SELECT decision FROM ai_decisions WHERE feature='coding_assistant' AND subject_id=? ORDER BY id DESC LIMIT 1", [s.claim_id]);
    const many = JSON.parse(s.suggestions).length > 1;
    expect(dec && dec.decision === (many ? 'edited' : 'accepted'), `governance decision ${dec && dec.decision}`);
    expect(one('SELECT stage FROM claims WHERE id=?', [s.claim_id]).stage === stage, 'claim stage changed by coding');
    const again = await post(b, `/claims/codes/${s.id}/decide`, { codes: 'A00' });
    expect(/already decided/.test(again.body), 'second decision accepted');
    await pages.owner.goto(`${BASE}/claims`);
    const ro = await post(pages.owner, `/claims/${s.claim_id}/codes/suggest`);
    expect(ro.status === 403, `owner suggest answered ${ro.status}`);
    const bc = one("SELECT id FROM claims WHERE branch_id='B' LIMIT 1");
    const rb = await post(b, `/claims/${bc.id}/codes/suggest`);
    expect(rb.status === 404, `branch-B claim answered ${rb.status}`);
  });

  await step(pages.nurse, 'P31 NEWS2: nurse records vitals, score is exact (14), emergency alert raised and acknowledged', async () => {
    const n = pages.nurse;
    await n.goto(`${BASE}/vitals`);
    const bed = py(['import json', 'from app.ai_features import news2', 'print(json.dumps(news2.inpatients("A")[0]))'].join('\n'));
    await n.getByRole('combobox', { name: /^Patient\b/ }).selectOption(String(bed.patient_id));
    await n.getByLabel('Respiration /min').fill('25');      // 3
    await n.getByLabel('SpO₂ %').fill('91');                // 3
    await n.getByLabel('Air or oxygen').selectOption({ index: 0 }); // air, 0
    await n.getByLabel('Systolic BP mmHg').fill('90');      // 3
    await n.getByLabel('Pulse /min').fill('131');           // 3
    await n.getByLabel('Consciousness (ACVPU)').selectOption('A'); // 0
    await n.getByLabel('Temperature °C').fill('39.5');      // 2
    await n.getByRole('button', { name: 'Save and score' }).click();
    await n.waitForLoadState('domcontentloaded');
    const f = await flash(n);
    expect(/NEWS2 14\b/.test(f.msg) && /Emergency alert/i.test(f.msg), `toast: ${JSON.stringify(f)}`);
    const v = one('SELECT news2, on_oxygen FROM vitals WHERE patient_id=? ORDER BY id DESC LIMIT 1', [bed.patient_id]);
    expect(v.news2 === 14 && v.on_oxygen === 0, JSON.stringify(v));
    const a = one("SELECT id, level, status FROM news2_alerts WHERE patient_id=? ORDER BY id DESC LIMIT 1", [bed.patient_id]);
    expect(a.level === 'emergency' && a.status === 'Open', JSON.stringify(a));
    const bad = await post(n, '/vitals', { patient_id: String(bed.patient_id), resp_rate: '18', spo2: 'abc', systolic_bp: '120', pulse: '80', consciousness: 'A', temperature: '37' });
    expect(/Fill in every vital sign as a number/.test(bad.body), 'non-number SpO2 not refused cleanly');
    await n.goto(`${BASE}/vitals`);
    const openBefore = one("SELECT COUNT(*) n FROM news2_alerts WHERE status='Open' AND branch_id='A'").n;
    await n.getByRole('button', { name: 'Acknowledge' }).first().click();
    await n.waitForLoadState('domcontentloaded');
    expect(one("SELECT COUNT(*) n FROM news2_alerts WHERE status='Open' AND branch_id='A'").n === openBefore - 1, 'acknowledge did not close one alert');
    await pages.frontb.goto(`${BASE}/vitals`);
    const other = one("SELECT id FROM news2_alerts WHERE branch_id='A' AND status='Open' LIMIT 1");
    if (other) {
      const r = await post(pages.frontb, `/vitals/alerts/${other.id}/ack`);
      expect(r.status === 404, `branch-B user acknowledged a branch-A alert (HTTP ${r.status})`);
    }
  });

  await step(pages.doctor, 'P32 explainers: text that interprets a result is refused; edits go back to Draft', async () => {
    const d = pages.doctor;
    await d.goto(`${BASE}/explainers`);
    const r = await post(d, '/explainers', { test_code: 'HCT', lang: 'en', body: 'Your result is high, please rest.' });
    expect(/must not talk about the patient(&#39;|')s own result/.test(r.body), 'interpreting text accepted');
    const ok = await post(d, '/explainers', { test_code: 'K', lang: 'en', body: 'Potassium is a mineral that helps the heart and muscles work. QA edit.' });
    expect(/Saved as a draft/.test(ok.body), 'save not confirmed');
    expect(one("SELECT status FROM report_explainers WHERE test_code='K' AND lang='en'").status === 'Draft', 'edit kept Approved status');
    const ap = await post(d, '/explainers/approve', { test_code: 'K', lang: 'en' });
    expect(/Approved/.test(ap.body), 'approve not confirmed');
  });

  // ------------------------------------------------ patient app: reports and voice
  const pt = await newRolePage(browser, { width: 390, height: 844 });
  let patientIn = false;
  await step(pt, 'P33 patient OTP login (lab patient from P11)', async () => {
    await pt.goto(`${BASE}/my/login`);
    await pt.getByLabel(/mobile number/i).fill(P1.phone);
    await pt.getByRole('button', { name: /get code/i }).click();
    await pt.getByLabel(/code/i).waitFor();
    const m = one("SELECT body FROM messages WHERE to_phone=? AND template='patient_otp' ORDER BY id DESC LIMIT 1", ['91' + P1.phone]);
    const code = (m.body.match(/\b(\d{6})\b/) || [])[1];
    await pt.getByLabel(/code/i).fill(code);
    await pt.getByRole('button', { name: /log in/i }).click();
    await pt.waitForLoadState('domcontentloaded');
    expect(/\/my\/?$/.test(new URL(pt.url()).pathname), `not on /my: ${pt.url()}`);
    patientIn = true;
  });

  await step(pt, 'P34 /my report: validated K shows value + approved explainer; un-validated TSH shows no value', async () => {
    if (!patientIn || !st.p1k) return 'SKIP needs P11 and P33';
    await pt.goto(`${BASE}/my/reports/${st.p1k.order_id}`);
    const t = await text(pt);
    expect(/4\.2/.test(t), 'validated value not shown');
    expect(/What this test measures/.test(t) && /Potassium is a mineral/.test(t), 'approved explainer missing');
    expect(!/\b(normal|high|low)\b/i.test(t.split('What this test measures')[1] || ''), 'explainer interprets the result');
    if (st.p1tsh) {
      await pt.goto(`${BASE}/my/reports/${st.p1tsh.order_id}`);
      const u = await text(pt);
      expect(!/8\.4/.test(u), 'un-validated TSH value shown to the patient');
    }
    if (st.p2k) {
      const r = await pt.goto(`${BASE}/my/reports/${st.p2k.order_id}`);
      expect(!(await text(pt)).includes('6.8'), `another patient's result shown (HTTP ${r.status()})`);
    }
  });

  await step(pt, 'P35 /my/voice: consent required, CSRF required, book by voice creates one appointment', async () => {
    if (!patientIn) return 'SKIP patient not logged in';
    await pt.goto(`${BASE}/my/voice`);
    const token = await pt.locator('[data-csrf]').getAttribute('data-csrf');
    const call = (url, data, csrf = token) => pt.request.post(BASE + url, { data, headers: { 'X-CSRF-Token': csrf } });
    let r = await call('/voice/start', { mode: 'patient', lang: 'en-IN', consent: false });
    expect(r.status() === 400 && /agree/i.test((await r.json()).error), `start without consent: ${r.status()}`);
    r = await call('/voice/start', { mode: 'patient', lang: 'en-IN', consent: true }, 'wrong');
    expect(r.status() === 403, `start with a wrong CSRF token: ${r.status()}`);
    r = await call('/voice/start', { mode: 'patient', lang: 'en-IN', consent: true });
    expect(r.status() === 200, `start: ${r.status()}`);
    const vt = (await r.json()).token;
    const pid = one('SELECT id FROM patients WHERE phone=?', ['91' + P1.phone]).id;
    const before = one("SELECT COUNT(*) n FROM appointments WHERE patient_id=? AND source='Voice assistant'", [pid]).n;
    const say = async t => (await (await call('/voice/turn', { mode: 'patient', token: vt, text: t })).json());
    const a1 = await say('I want to book an appointment');
    expect(/1\./.test(a1.reply || ''), `doctor list: ${JSON.stringify(a1)}`);
    const a2 = await say('1');
    if (/no free|no slots/i.test(a2.reply || '')) return `SKIP no free slots: ${a2.reply}`;
    const a3 = await say('1');
    expect(a3.action === 'booked', `booking: ${JSON.stringify(a3)}`);
    expect(one("SELECT COUNT(*) n FROM appointments WHERE patient_id=? AND source='Voice assistant'", [pid]).n === before + 1, 'appointment not stored once');
    const em = await say('my father has chest pain and is unconscious');
    expect(em.action === 'emergency' && /108/.test(em.reply), `emergency: ${JSON.stringify(em)}`);
    return a3.reply.slice(0, 70);
  });

  await step(admin, 'P36 /voice/demo: page works by typing; unverified caller gets a call-back task, never a booking', async () => {
    const v = await newRolePage(browser, { width: 390, height: 844 });
    await v.goto(`${BASE}/voice/demo`);
    const ph = phoneFor(9);
    await v.getByLabel('Your mobile number').fill(ph);
    await v.getByLabel(/I agree/).check();
    await v.getByRole('button', { name: 'Start' }).click();
    await v.getByText(/I can book an appointment/).waitFor();
    await v.getByLabel('Or type your message').fill('book an appointment please');
    await v.getByRole('button', { name: 'Send' }).click();
    await v.getByText(/Our team will call you/).waitFor();
    expect(one("SELECT COUNT(*) n FROM appointments WHERE source='Voice assistant' AND patient_id IN (SELECT id FROM patients WHERE phone=?)", ['91' + ph]).n === 0, 'unverified caller booked');
    expect(one('SELECT COUNT(*) n FROM tasks WHERE title LIKE ?', [`%+91${ph}%`]).n === 1, 'no call-back task');
    await v.getByLabel('Or type your message').fill("what's my bill");
    await v.getByRole('button', { name: 'Send' }).click();
    await v.waitForTimeout(800);
    expect(!/₹/.test(await v.getByRole('list').last().innerText()), 'unverified caller told a bill amount');
    await v.context().close();
  });

  await step(admin, 'P37 no HTTP 5xx and no JS errors during the run', async () => {
    expect(serverErrors.length === 0, serverErrors.slice(0, 5).join('; '));
  });

  await browser.close();
  const c = s => results.filter(r => r.status === s).length;
  console.log(`\nRESULT: ${c('PASS')} passed, ${c('FAIL')} failed, ${c('SKIP')} skipped of ${results.length} steps`);
  try { fs.writeFileSync(path.join(SHOTS, 'pro_results.json'), JSON.stringify(results, null, 2)); } catch (_) { /* best effort */ }
  process.exit(c('FAIL') ? 1 : 0);
})().catch(e => { console.error('FATAL', e); process.exit(2); });
