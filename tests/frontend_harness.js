// מריץ את הסקריפט של web/index.html בסביבת דפדפן מדומה (בלי רשת), לבדיקות אוטומטיות.
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const HTML_PATH = path.join(__dirname, '..', 'web', 'index.html');

function makeEl(id) {
  const classes = new Set();
  return {
    id, _html: '', textContent: '', value: '', checked: false, style: {}, offsetHeight: 150, scrollTop: 0, dataset: {}, title: '',
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, force) => { const on = force === undefined ? !classes.has(c) : force; on ? classes.add(c) : classes.delete(c); return on; },
      contains: (c) => classes.has(c),
    },
    addEventListener() {}, appendChild() {}, remove() {}, insertAdjacentHTML() {}, scrollIntoView() {},
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    querySelectorAll() { return []; }, querySelector() { return null; },
  };
}

function jsonRes(body, ok = true, status = 200) {
  return { ok, status, json: async () => body, text: async () => JSON.stringify(body) };
}

function load({ hash = '', storage = {}, anonKey = 'sb_publishable_test', fetch: userFetch } = {}) {
  const els = {};
  const store = new Map(Object.entries(storage).map(([k, v]) => [k, typeof v === 'string' ? v : JSON.stringify(v)]));
  const calls = [];
  const win = { scrollY: 0, addEventListener() {}, location: { origin: 'https://user.github.io', pathname: '/lekanot/', search: '', hash, href: '' } };
  const defaultFetch = async (url) => {
    const u = String(url);
    if (u.includes('/auth/v1/settings')) return jsonRes({ external: { google: false, email: true } });
    return jsonRes([]);
  };
  const doFetch = async (url, opts = {}) => {
    calls.push({ url: decodeURIComponent(String(url)), method: opts.method || 'GET', headers: opts.headers || {}, body: opts.body });
    return (userFetch ? await userFetch(String(url), opts) : undefined) ?? defaultFetch(url, opts);
  };
  const ctx = {
    document: { getElementById: (id) => els[id] || (els[id] = makeEl(id)), createElement: () => makeEl(), querySelectorAll: () => [], body: { appendChild() {} }, documentElement: { style: { setProperty() {} } } },
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, String(v)); }, removeItem: (k) => { store.delete(k); } },
    history: { replaceState(_a, _b, url) { win.location.hash = ''; ctx.history.lastUrl = url; } },
    fetch: doFetch, window: win, navigator: { clipboard: { writeText: async () => {} } },
    console, alert() {}, prompt: () => null, URLSearchParams, URL, setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0,
    requestAnimationFrame: (f) => f(), MutationObserver: class { observe() {} },
    Map, Set, Number, Date, JSON, Object, Array, Math, String, Promise, Intl, isNaN, parseInt, parseFloat, encodeURIComponent, decodeURIComponent,
  };
  vm.createContext(ctx);
  // בריפו המפתחות האמיתיים מוזרקים לקובץ, ובפיתוח הם placeholders - מנטרלים את שני המצבים
  const html = fs.readFileSync(HTML_PATH, 'utf8')
    .replace(/const SUPABASE_URL = "[^"]*";/, 'const SUPABASE_URL = "https://proj.supabase.co";')
    .replace(/const SUPABASE_ANON_KEY = "[^"]*";/, `const SUPABASE_ANON_KEY = ${JSON.stringify(anonKey)};`);
  vm.runInContext(html.match(/<script>([\s\S]*)<\/script>/)[1], ctx);
  vm.runInContext('globalThis.__t = { state, auth, loc, LS, AUTH_LS }', ctx);
  return { ctx, els, store, calls, win, t: ctx.__t, html };
}

async function settle(n = 25) { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); }
const priceOffer = (id, chain, name, price, o = {}) => ({ id, price, price_max: o.max ?? price, unit_price: null, in_stock: o.in_stock ?? true, stores_carrying: o.carry ?? 1, store_id: 'S' + chain, stores: { name: 'כל הסניפים', city: null, chain_id: chain, chains: { display_name: name } } });

module.exports = { load, settle, jsonRes, priceOffer };
