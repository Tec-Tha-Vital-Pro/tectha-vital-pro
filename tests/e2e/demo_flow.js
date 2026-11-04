#!/usr/bin/env node
/*
 * End-to-end demo flow (docs/DEMO_SCRIPT.md) against a RUNNING server.
 *
 *   node tests/e2e/demo_flow.js
 *
 * Environment (defaults match docs/TEST_PLAN.md section 6):
 *   E2E_BASE_URL     http://127.0.0.1:8020
 *   TT_DB_PATH       the server's SQLite file (read-only use: find phones, read the OTP, check money math)
 *   TT_API_KEY       qa-key   (missed-call webhook)
 *   E2E_USER / E2E_PASSWORD   admin / Qa@12345
 *   E2E_SHOTS        directory for failure screenshots
 *   E2E_HEADED=1     watch the browser
 *
 * Selectors use visible text, labels and roles only (no CSS classes) so the
 * script survives the redesign. Prints PASS / FAIL / SKIP per step and exits 1
 * if any step fails. Needs a freshly seeded database (python -m app.seed).
 */
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const BASE = (process.env.E2E_BASE_URL || 'http://127.0.0.1:8020').replace(/\/$/, '');
const DB = process.env.TT_DB_PATH || '';
const API_KEY = process.env.TT_API_KEY || 'qa-key';
const USER = process.env.E2E_USER || 'admin';
const PASSWORD = process.env.E2E_PASSWORD || 'Qa@12345';
const SHOTS = process.env.E2E_SHOTS ||
  '/tmp/claude-0/-home-user/5f540028-1c92-5b5c-889b-342c486a270d/scratchpad/qa';

const results = [];

// ---------------------------------------------------------------- helpers

/** Read-only SQL against the server's database through Python's sqlite3. */
function sql(query, params = []) {
  if (!DB) throw new Error('TT_DB_PATH is not set; the DB checks need it');
  const py = [
    'import json, sqlite3, sys',
    'c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)',
    'c.row_factory = sqlite3.Row',
    'rows = [dict(r) for r in c.execute(sys.argv[2], json.loads(sys.argv[3]))]',
    'print(json.dumps(rows))',
  ].join('\n');
  const out = execFileSync('python3', ['-c', py, DB, query, JSON.stringify(params)], { encoding: 'utf8' });
  return JSON.parse(out);
}
const one = (q, p) => sql(q, p)[0];

function expect(cond, msg) {
  if (!cond) throw new Error(msg);
}

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
    return true;
  } catch (e) {
    const file = path.join(SHOTS, `fail-${String(results.length + 1).padStart(2, '0')}-${name.replace(/[^a-z0-9]+/gi, '_')}.png`);
    try { await page.screenshot({ path: file, fullPage: true }); } catch (_) { /* page may be gone */ }
    const msg = (e && e.message ? e.message : String(e)).split('\n')[0];
    results.push({ name, status: 'FAIL', note: msg, screenshot: file });
    console.log(`FAIL  ${name} - ${msg}\n      url: ${page.url()}\n      screenshot: ${file}`);
    return false;
  }
}

/** The flash message after a POST/redirect. The page's JS strips ?msg / ?err from the address bar,
 *  so read them from the last main-frame document response, falling back to the current URL. */
const lastDoc = new WeakMap();
function trackDocs(page) {
  page.on('response', r => {
    if (r.request().resourceType() === 'document' && r.frame() === page.mainFrame()) lastDoc.set(page, r.url());
  });
}
function flash(page) {
  const u = new URL(lastDoc.get(page) || page.url());
  return { msg: u.searchParams.get('msg') || '', err: u.searchParams.get('err') || '' };
}

/** Type a patient message into the simulator box on Messages and send it. Throws if the server rejects it. */
async function simulate(page, phone, text) {
  await page.getByLabel(/patient mobile/i).fill(phone);
  await page.getByLabel(/^message$/i).fill(text);
  const [resp] = await Promise.all([
    page.waitForResponse(r => r.url().includes('/webhooks/simulate-inbound') && r.request().method() === 'POST'),
    page.getByRole('button', { name: /send as patient/i }).click(),
  ]);
  await page.waitForLoadState('domcontentloaded');
  if (resp.status() >= 400) {
    throw new Error(`simulator POST returned ${resp.status()}: ${(await resp.text()).slice(0, 120)}`);
  }
}

async function bodyText(page) {
  return page.locator('body').innerText();
}

// ---------------------------------------------------------------- flow

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ headless: process.env.E2E_HEADED !== '1' });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.setDefaultTimeout(10000);
  trackDocs(page);
  const serverErrors = [];
  page.on('response', r => {
    if (r.status() >= 500) serverErrors.push(`${r.status()} ${r.url()}`);
    if (r.status() === 403 && r.request().method() === 'POST') serverErrors.push(`403 on POST ${r.url()}`);
  });

  const ctxState = {};

  await step(page, '00 server health (/api/health)', async () => {
    const r = await page.request.get(`${BASE}/api/health`);
    expect(r.ok(), `health returned ${r.status()}`);
    if (DB) {
      const n = one('SELECT COUNT(*) AS n FROM branches').n;
      expect(n >= 2, `expected 2 seeded branches, found ${n} (run python -m app.seed)`);
    }
  });

  await step(page, '01 unauthenticated / redirects to login', async () => {
    await page.goto(`${BASE}/`);
    expect(/\/login/.test(page.url()), `expected redirect to /login, got ${page.url()}`);
  });

  await step(page, '02 wrong password is rejected', async () => {
    await page.goto(`${BASE}/login`);
    await page.getByLabel('Username').fill(USER);
    await page.getByLabel('Password').fill('definitely-wrong');
    await page.getByRole('button', { name: /log in/i }).click();
    await page.getByText(/wrong username or password/i).waitFor();
  });

  const loggedIn = await step(page, '03 admin login', async () => {
    await page.goto(`${BASE}/login`);
    await page.getByLabel('Username').fill(USER);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByRole('button', { name: /log in/i }).click();
    await page.waitForLoadState('domcontentloaded');
    expect(!/\/login/.test(page.url()), `still on login page: ${page.url()}`);
  });
  if (!loggedIn) return finish(browser, serverErrors);

  await step(page, '04 dashboard renders KPIs and Needs attention', async () => {
    await page.goto(`${BASE}/`);
    await page.getByRole('heading', { level: 1 }).first().waitFor();
    const text = await bodyText(page);
    for (const label of ['Outstanding dues', 'No-show', 'Needs attention']) {
      expect(new RegExp(label, 'i').test(text), `dashboard is missing "${label}"`);
    }
    expect(/₹\d/.test(text), 'no rupee amounts on the dashboard');
    const dues = one('SELECT COALESCE(SUM(total-paid),0) AS d FROM bills WHERE total>paid').d;
    const inr = '₹' + Number(dues).toLocaleString('en-IN');
    expect(text.includes(inr), `dashboard does not show outstanding dues ${inr} from the database`);
    expect(await page.locator('svg').count() > 0, 'no chart (svg) on the dashboard');
    return `dues ${inr}`;
  });

  await step(page, '05 dashboard branch switch shows one branch', async () => {
    const b = one("SELECT id, name FROM branches ORDER BY id LIMIT 1");
    await page.goto(`${BASE}/?branch=${b.id}`);
    const dues = one('SELECT COALESCE(SUM(total-paid),0) AS d FROM bills WHERE total>paid AND branch_id=?', [b.id]).d;
    const inr = '₹' + Number(dues).toLocaleString('en-IN');
    expect((await bodyText(page)).includes(inr), `branch ${b.id} view does not show its dues ${inr}`);
    return `${b.name} dues ${inr}`;
  });

  await step(page, '06 Settings -> Run automations now', async () => {
    ctxState.outBefore = one("SELECT COUNT(*) AS n FROM messages WHERE direction='out'").n;
    await page.goto(`${BASE}/settings`);
    await page.getByRole('button', { name: /run automations now/i }).click();
    await page.waitForLoadState('domcontentloaded');
    const f = flash(page);
    const text = f.msg + ' ' + (await bodyText(page));
    expect(/automations ran/i.test(text), `no "Automations ran" confirmation (err=${f.err})`);
    ctxState.outAfter = one("SELECT COUNT(*) AS n FROM messages WHERE direction='out'").n;
    const rem = one("SELECT COUNT(*) AS n FROM messages WHERE template LIKE 'appt_reminder_%'").n;
    expect(rem > 0, 'no appointment reminders were created');
    return `${ctxState.outAfter - ctxState.outBefore} new outbound messages, ${rem} appointment reminders`;
  });

  await step(page, '07 automations are idempotent (second run sends nothing new)', async () => {
    const before = sql("SELECT template, COUNT(*) AS n FROM messages WHERE direction='out' AND template<>'owner_daily_report' GROUP BY template");
    await page.goto(`${BASE}/settings`);
    await page.getByRole('button', { name: /run automations now/i }).click();
    await page.waitForLoadState('domcontentloaded');
    const after = sql("SELECT template, COUNT(*) AS n FROM messages WHERE direction='out' AND template<>'owner_daily_report' GROUP BY template");
    const b = Object.fromEntries(before.map(r => [r.template, r.n]));
    const diff = after.filter(r => r.n !== (b[r.template] || 0)).map(r => `${r.template} +${r.n - (b[r.template] || 0)}`);
    expect(diff.length === 0, `second run sent more messages: ${diff.join(', ')}`);
  });

  await step(page, '08 Messages screen shows a reminder', async () => {
    // A patient whose latest outbound message is an appointment reminder (so a reply of 1 applies to it).
    const r = one(
      "SELECT m.to_phone, m.related_id, m.body FROM messages m WHERE m.template LIKE 'appt_reminder_%' AND m.status='simulated'" +
      " AND m.id = (SELECT MAX(id) FROM messages x WHERE x.to_phone=m.to_phone AND x.direction='out') ORDER BY m.id DESC LIMIT 1");
    expect(r, 'no conversation whose last message is a reminder');
    ctxState.rem = r;
    await page.goto(`${BASE}/messages?phone=${r.to_phone}`);
    await page.getByText(/reply 1 to confirm/i).first().waitFor();
    return `+${r.to_phone}, OPD-${r.related_id}`;
  });

  await step(page, '09 simulate inbound "1" -> appointment Confirmed', async () => {
    const r = ctxState.rem;
    expect(r, 'depends on step 08');
    await page.goto(`${BASE}/messages?phone=${r.to_phone}`);
    await simulate(page, r.to_phone, '1');
    const a = one('SELECT status, starts_at FROM appointments WHERE id=?', [r.related_id]);
    expect(a.status === 'Confirmed', `appointment OPD-${r.related_id} is ${a.status}, expected Confirmed`);
    await page.goto(`${BASE}/messages?phone=${r.to_phone}`);
    await page.getByText(/appointment is confirmed/i).first().waitFor();
    await page.goto(`${BASE}/appointments?day=${a.starts_at.slice(0, 10)}`);
    const row = page.getByRole('row').filter({ hasText: one('SELECT p.name FROM appointments a JOIN patients p ON p.id=a.patient_id WHERE a.id=?', [r.related_id]).name });
    expect(/confirmed/i.test(await row.first().innerText()), 'Appointments screen does not show Confirmed for that patient');
  });

  await step(page, '10 simulate inbound "2" after feedback request -> complaint task', async () => {
    const r = one(
      "SELECT m.to_phone, p.name FROM messages m JOIN patients p ON p.id=m.patient_id WHERE m.template='feedback_request' AND m.status='simulated'" +
      " AND m.id = (SELECT MAX(id) FROM messages x WHERE x.to_phone=m.to_phone AND x.direction='out') ORDER BY m.id DESC LIMIT 1");
    if (!r) return 'SKIP no patient whose last message is a feedback request in this seed';
    const before = one("SELECT COUNT(*) AS n FROM tasks WHERE kind='complaint' AND status='Open'").n;
    await page.goto(`${BASE}/messages?phone=${r.to_phone}`);
    await simulate(page, r.to_phone, '2');
    const after = one("SELECT COUNT(*) AS n FROM tasks WHERE kind='complaint' AND status='Open'").n;
    expect(after === before + 1, `complaint tasks ${before} -> ${after}, expected +1`);
    await page.goto(`${BASE}/tasks`);
    await page.getByText(new RegExp(`Low feedback score 2/5 from ${r.name}`)).first().waitFor();
  });

  await step(page, '11 message from a new number -> enquiry in inbox', async () => {
    const phone = '9' + String(Date.now()).slice(-9);
    await page.goto(`${BASE}/messages`);
    await simulate(page, phone, 'Need an orthopaedic appointment tomorrow');
    const lead = one('SELECT id FROM leads WHERE phone=?', ['91' + phone]);
    expect(lead, 'no lead created for the new number');
    await page.goto(`${BASE}/leads`);
    await page.getByText(/need an orthopaedic appointment/i).first().waitFor();
  });

  await step(page, '12 missed-call API -> lead and 15-minute task', async () => {
    const bad = await page.request.post(`${BASE}/webhooks/missed-call`, { data: { phone: '9811100022' } });
    expect(bad.status() === 401, `no key should be 401, got ${bad.status()}`);
    const r = await page.request.post(`${BASE}/webhooks/missed-call`,
      { data: { phone: '9811100022', branch_id: 'A' }, headers: { 'X-API-Key': API_KEY } });
    expect(r.ok(), `missed-call returned ${r.status()}`);
    const j = await r.json();
    const t = one('SELECT due_at, created_at FROM tasks WHERE id=?', [j.task_id]);
    const mins = (Date.parse(t.due_at.replace(' ', 'T')) - Date.parse(t.created_at.replace(' ', 'T'))) / 60000;
    expect(mins === 15, `task due in ${mins} min, expected 15`);
  });

  await step(page, '13 billing: Send reminder now', async () => {
    await page.goto(`${BASE}/billing`);
    const before = one("SELECT COUNT(*) AS n FROM messages WHERE template='dues_reminder'").n;
    const btn = page.getByRole('button', { name: /send reminder/i }).first();
    expect(await btn.count() > 0, 'no "Send reminder" button on Billing');
    await btn.click();
    await page.waitForLoadState('domcontentloaded');
    const f = flash(page);
    const after = one("SELECT COUNT(*) AS n FROM messages WHERE template='dues_reminder'").n;
    expect(after === before + 1, `dues_reminder messages ${before} -> ${after} (msg=${f.msg} err=${f.err})`);
    const m = one("SELECT body, status FROM messages WHERE template='dues_reminder' ORDER BY id DESC LIMIT 1");
    if (m.status === 'blocked_no_consent') {
      expect(/consent/i.test(f.err), 'blocked send without a consent error on screen');
      return 'patient had no consent: blocked and explained (correct)';
    }
    expect(/reminder sent/i.test(f.msg), `no success message (err=${f.err})`);
    expect(/https?:\/\/\S+/.test(m.body) && /Balance due\s+₹/.test(m.body), 'reminder text has no payment link or balance');
  });

  await step(page, '14 billing: Record payment updates the balance exactly', async () => {
    await page.goto(`${BASE}/billing`);
    const btn = page.getByRole('button', { name: /record payment/i }).first();
    expect(await btn.count() > 0, 'no "Record payment" button');
    await btn.click();
    const dlg = page.getByRole('dialog').filter({ has: page.getByLabel(/amount/i) }).first();
    await dlg.waitFor();
    const amt = dlg.getByLabel(/amount/i);
    const max = Number(await amt.getAttribute('max'));
    const id = Number((await dlg.locator('form').getAttribute('action')).match(/\/billing\/(\d+)\/payment/)[1]);
    const b0 = one('SELECT total, paid FROM bills WHERE id=?', [id]);
    expect(max === b0.total - b0.paid, `form max ${max} != balance ${b0.total - b0.paid}`);
    const pay = Math.min(100, max);
    await amt.fill(String(pay));
    await dlg.getByRole('button', { name: /save payment/i }).click();
    await page.waitForLoadState('domcontentloaded');
    const b1 = one('SELECT total, paid FROM bills WHERE id=?', [id]);
    expect(b1.paid === b0.paid + pay && b1.total === b0.total, `paid ${b0.paid} -> ${b1.paid}, expected +${pay}`);
    const sum = one('SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE bill_id=?', [id]).s;
    expect(sum === b1.paid, `bills.paid ${b1.paid} != sum(payments) ${sum}`);
    return `bill ${id}: paid +₹${pay}`;
  });

  await step(page, '15 billing: Add to bill moves the order onto a bill', async () => {
    await page.goto(`${BASE}/billing`);
    const buttons = page.getByRole('button', { name: /^add to bill$/i });
    const n0 = await buttons.count();
    if (n0 === 0) return 'SKIP no unbilled services in this seed';
    const form = buttons.first().locator('xpath=ancestor::form[1]');
    const oid = Number((await form.getAttribute('action')).match(/orders\/(\d+)\/add/)[1]);
    const o = one('SELECT amount, patient_id, branch_id FROM orders WHERE id=?', [oid]);
    await buttons.first().click();
    await page.waitForLoadState('domcontentloaded');
    const f = flash(page);
    expect(/added to bill/i.test(f.msg), `no "Added to bill" message (err=${f.err})`);
    const o1 = one('SELECT bill_id FROM orders WHERE id=?', [oid]);
    expect(o1.bill_id, 'order still has no bill');
    const b = one('SELECT total FROM bills WHERE id=?', [o1.bill_id]);
    const items = one('SELECT SUM(amount) AS s FROM bill_items WHERE bill_id=?', [o1.bill_id]).s;
    expect(b.total === items, `bill total ${b.total} != sum of items ${items}`);
    const open = one("SELECT COUNT(*) AS n FROM tasks WHERE kind='unbilled' AND related_id=? AND status='Open'", [oid]).n;
    expect(open === 0, 'the unbilled task is still open');
    expect(await page.getByRole('button', { name: /^add to bill$/i }).count() === n0 - 1, 'unbilled list did not shrink by one');
    return `order ${oid} (₹${o.amount}) -> bill ${o1.bill_id}`;
  });

  await step(page, '16 claims board loads with stuck claims flagged', async () => {
    await page.goto(`${BASE}/claims`);
    await page.getByRole('heading', { level: 1 }).first().waitFor();
    const text = await bodyText(page);
    expect(/pre-auth requested/i.test(text), 'no "Pre-auth requested" column');
    const stuck = one("SELECT COUNT(*) AS n FROM tasks WHERE kind='claim_stuck' AND status='Open'").n;
    expect(stuck > 0, 'automations created no stuck-claim tasks (seed has a claim past 1 h)');
    return `${stuck} stuck claims`;
  });

  await step(page, '17 owner report generated and shown on dashboard', async () => {
    const r = one("SELECT body FROM messages WHERE template='owner_daily_report' ORDER BY id DESC LIMIT 1");
    const hour = Number(new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(11, 13));
    if (!r && hour < 9) return 'SKIP before 9 am IST, the report is not due yet';
    expect(r, 'no owner report after 9 am IST');
    expect(/Needs attention/.test(r.body) && /₹/.test(r.body), 'report has no attention block or rupee figures');
    await page.goto(`${BASE}/`);
    expect(/last sent/i.test(await bodyText(page)), 'dashboard does not show the last report');
  });

  // ---- patient app (/my), only if it exists
  const pctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const pp = await pctx.newPage();
  pp.setDefaultTimeout(10000);
  trackDocs(pp);
  pp.on('response', r => { if (r.status() >= 500) serverErrors.push(`${r.status()} ${r.url()}`); });

  const pat = DB ? one(
    "SELECT p.id, p.phone, p.name, b.id AS bill_id, b.total - b.paid AS bal FROM patients p JOIN bills b ON b.patient_id=p.id" +
    " WHERE b.total > b.paid ORDER BY b.id DESC LIMIT 1") : null;
  let patientIn = false;

  await step(pp, '18 patient app: OTP login', async () => {
    const r = await pp.goto(`${BASE}/my/login`);
    if (!r || r.status() === 404) return 'SKIP /my is not deployed';
    expect(pat, 'no patient with a pending bill in the seed');
    await pp.getByLabel(/mobile number/i).fill(pat.phone.slice(2));
    await pp.getByRole('button', { name: /get code/i }).click();
    await pp.getByLabel(/^code$/i).waitFor();
    const m = one("SELECT body FROM messages WHERE to_phone=? AND template='patient_otp' ORDER BY id DESC LIMIT 1", [pat.phone]);
    expect(m, 'no OTP message stored');
    const code = (m.body.match(/\b(\d{6})\b/) || [])[1];
    expect(code, 'no 6-digit code in the OTP message');
    expect(!(await bodyText(pp)).includes(code), 'the OTP is shown on the login page');
    await pp.getByLabel(/^code$/i).fill(code);
    await pp.getByRole('button', { name: /log in/i }).click();
    await pp.waitForLoadState('domcontentloaded');
    expect(/\/my\/?$/.test(new URL(pp.url()).pathname), `not on patient home: ${pp.url()}`);
    patientIn = true;
    return pat.name;
  });

  await step(pp, '19 patient app: book a visit', async () => {
    if (!patientIn) return 'SKIP patient not logged in';
    const doc = one('SELECT id, branch_id FROM doctors ORDER BY id LIMIT 1');
    const before = one("SELECT COUNT(*) AS n FROM appointments WHERE patient_id=? AND source='Patient app'", [pat.id]).n;
    // Walk the four steps by clicking links (branch, doctor, a day that has free slots).
    await pp.goto(`${BASE}/my/book`);
    await pp.getByRole('link', { name: new RegExp(one('SELECT name FROM branches WHERE id=?', [doc.branch_id]).name) }).first().click();
    await pp.getByRole('link', { name: new RegExp(one('SELECT name FROM doctors WHERE id=?', [doc.id]).name.replace(/\./g, '\\.')) }).first().click();
    const days = pp.getByRole('link', { name: /\d/ }).filter({ has: pp.locator('strong') });
    const nDays = await days.count();
    let booked = false;
    for (let i = 1; i < Math.max(2, nDays) && !booked; i++) {   // tomorrow onward: today may have no slots left
      await days.nth(Math.min(i, nDays - 1)).click();
      const radio = pp.getByRole('radio').first();
      if (await radio.count() === 0) { await pp.goBack(); continue; }
      await radio.check();
      await pp.getByRole('button', { name: /confirm booking/i }).click();
      await pp.waitForLoadState('domcontentloaded');
      booked = true;
    }
    expect(booked, 'no free slot found on any day');
    const after = one("SELECT COUNT(*) AS n FROM appointments WHERE patient_id=? AND source='Patient app'", [pat.id]).n;
    expect(after === before + 1, `patient-app appointments ${before} -> ${after}`);
    expect(/booked/i.test(await bodyText(pp)), 'no booking confirmation on screen');
  });

  await step(pp, '20 patient app: pay a pending bill (demo payment)', async () => {
    if (!patientIn) return 'SKIP patient not logged in';
    const b0 = one('SELECT total, paid FROM bills WHERE id=?', [pat.bill_id]);
    if (b0.total - b0.paid <= 0) return 'SKIP bill already paid by an earlier step';
    await pp.goto(`${BASE}/my/bills/${pat.bill_id}/pay`);
    expect(/demo/i.test(await bodyText(pp)), 'pay page does not say DEMO / no real money charged');
    const bal = '₹' + (b0.total - b0.paid).toLocaleString('en-IN');
    await pp.getByRole('button', { name: new RegExp('^Pay ' + bal.replace(/[₹,]/g, m => '\\' + m)) }).click();
    await pp.waitForLoadState('domcontentloaded');
    const b1 = one('SELECT total, paid FROM bills WHERE id=?', [pat.bill_id]);
    expect(b1.paid === b1.total, `bill paid ${b1.paid} of ${b1.total}`);
    return `paid ${bal}`;
  });

  await step(pp, '21 patient cannot open another patient\'s bill', async () => {
    if (!patientIn) return 'SKIP patient not logged in';
    const other = one('SELECT id FROM bills WHERE patient_id<>? ORDER BY id LIMIT 1', [pat.id]);
    await pp.goto(`${BASE}/my/bills/${other.id}`);
    const t = await bodyText(pp);
    const otherNo = one('SELECT bill_no FROM bills WHERE id=?', [other.id]).bill_no;
    expect(!t.includes(otherNo), `patient can see bill ${otherNo} of another patient`);
  });

  await step(page, '22 no server errors (HTTP 5xx, 403 on POST) during the run', async () => {
    expect(serverErrors.length === 0, serverErrors.join('; '));
  });

  await finish(browser, serverErrors);
})().catch(e => {
  console.error('FATAL', e);
  process.exit(2);
});

async function finish(browser) {
  await browser.close();
  const c = s => results.filter(r => r.status === s).length;
  console.log(`\nRESULT: ${c('PASS')} passed, ${c('FAIL')} failed, ${c('SKIP')} skipped of ${results.length} steps`);
  try {
    fs.writeFileSync(path.join(SHOTS, 'e2e_results.json'), JSON.stringify(results, null, 2));
  } catch (_) { /* best effort */ }
  process.exit(c('FAIL') ? 1 : 0);
}
