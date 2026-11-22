const test = require('node:test');
const assert = require('node:assert/strict');
const { load, settle, jsonRes, priceOffer } = require('./frontend_harness');

const nowSec = () => Math.floor(Date.now() / 1000);
const USER = { id: 'u1', email: 'dana@example.com', user_metadata: { full_name: 'דנה כהן', avatar_url: 'https://img/a.png' } };
const loggedInStorage = (extra = {}) => ({ 'lekanot:auth': { access_token: 'AT', refresh_token: 'RT', expires_at: nowSec() + 3000, user: USER }, ...extra });

// ------------------------------------------------------------------ עיצוב (המשוב האחרון)
test('notebook: no edge strip, nothing clips the spiral, real spiral drawn', () => {
  const { html } = load();
  assert.ok(!/\.notebook::before/.test(html), 'the gold dashed strip on the notebook edge must be gone');
  const rule = html.match(/\.notebook\{[^}]*\}/)[0];
  assert.ok(!/overflow:\s*hidden/.test(rule), 'overflow:hidden would clip the spiral rings');
  assert.match(html, /\.notebook \.coil span::after\{[^}]*linear-gradient/, 'metal wire drawn');
  assert.match(html, /\.notebook \.coil span::before\{[^}]*inset/, 'paper hole drawn');
});

test('chain switcher sits above the bottom bar, not under it', () => {
  const { html } = load();
  const bottom = Number(html.match(/\.shop-switcher\{[^}]*bottom:calc\((\d+)px/)[1]);
  const navZ = Number(html.match(/\.navbar\{[^}]*z-index:(\d+)/)[1]);
  const swZ = Number(html.match(/\.shop-switcher\{[^}]*z-index:(\d+)/)[1]);
  assert.ok(bottom >= 80, `switcher bottom=${bottom}px must clear the navbar`);
  assert.ok(swZ < navZ, 'and must not fight the navbar for the same layer');
});

test('compare button: floating, only on the cart page and only with items, shows the count', () => {
  const { ctx, els, html } = load();
  assert.match(html, /\.compare-fab\{position:fixed/);
  assert.ok(!/goCompareBtn|compare-glow-wrap/.test(html), 'old inline button removed');
  ctx.openPage('pageCart');
  assert.ok(!els.compareFab.classList.contains('show'), 'empty cart: hidden');
  ctx.addToCart({ id: 'p1', canonical_name: 'חלב', is_weighted: false }, 1);
  ctx.addToCart({ id: 'p2', canonical_name: 'לחם', is_weighted: false }, 2);
  assert.ok(els.compareFab.classList.contains('show'), 'items in cart on the cart page: visible');
  assert.match(els.compareFabText.textContent, /קח אותי להשוואה · 2/);
  ctx.closeAllPages();
  assert.ok(!els.compareFab.classList.contains('show'), 'leaving the cart page hides it');
});

// ------------------------------------------------------------------ חשבונות
test('Google not enabled on the server -> button is disabled (honest), email option still there', async () => {
  const { ctx, els } = load();
  await settle();
  await ctx.renderSettingsPage();
  const h = els.settingsContent.innerHTML;
  assert.match(h, /id="googleBtn"[^>]*disabled/);
  assert.match(h, /עדיין לא הופעלה בשרת/);
  assert.match(h, /id="emailBtn"/);
});

test('Google enabled on the server -> button is active', async () => {
  const { ctx, els } = load({ fetch: async (u) => (u.includes('/auth/v1/settings') ? jsonRes({ external: { google: true, email: true } }) : undefined) });
  await settle();
  await ctx.renderSettingsPage();
  assert.ok(!/id="googleBtn"[^>]*disabled/.test(els.settingsContent.innerHTML));
});

test('OAuth redirect: tokens in the URL hash become a session, the hash is cleaned, avatar shown', async () => {
  const { t, win, store, els, calls } = load({
    hash: '#access_token=AT1&refresh_token=RT1&expires_in=3600&token_type=bearer',
    fetch: async (u) => (u.includes('/auth/v1/user') ? jsonRes(USER) : undefined),
  });
  await settle();
  assert.equal(t.auth.session.access_token, 'AT1');
  assert.equal(t.auth.session.user.email, 'dana@example.com');
  assert.equal(win.location.hash, '', 'tokens must not stay in the address bar');
  assert.ok(JSON.parse(store.get('lekanot:auth')).refresh_token === 'RT1', 'session persisted');
  assert.match(els.avatarBtn.innerHTML, /img src="https:\/\/img\/a\.png"/);
  const userCall = calls.find(c => c.url.includes('/auth/v1/user'));
  assert.equal(userCall.headers.Authorization, 'Bearer AT1');
});

test('OAuth error in the hash -> no session, no crash', async () => {
  const { t } = load({ hash: '#error=access_denied&error_description=User+cancelled' });
  await settle();
  assert.equal(t.auth.session, null);
});

test('expired session is refreshed automatically before it is used', async () => {
  const { t, calls } = load({
    storage: { 'lekanot:auth': { access_token: 'OLD', refresh_token: 'RT', expires_at: nowSec() - 100, user: USER } },
    fetch: async (u) => (u.includes('grant_type=refresh_token') ? jsonRes({ access_token: 'NEW', refresh_token: 'RT2', expires_in: 3600, user: USER }) : undefined),
  });
  await settle();
  assert.equal(t.auth.session.access_token, 'NEW');
  const call = calls.find(c => c.url.includes('grant_type=refresh_token'));
  assert.equal(JSON.parse(call.body).refresh_token, 'RT');
});

test('refresh failure -> back to guest mode, public data keeps working', async () => {
  const { t, store, ctx } = load({
    storage: { 'lekanot:auth': { access_token: 'OLD', refresh_token: 'BAD', expires_at: nowSec() - 100, user: USER } },
    fetch: async (u) => (u.includes('grant_type=refresh_token') ? jsonRes({}, false, 400) : undefined),
  });
  await settle();
  assert.equal(t.auth.session, null);
  assert.equal(store.has('lekanot:auth'), false);
  assert.equal(ctx.sbHeaders().Authorization, undefined, 'with a publishable key, guests send no Authorization header');
});

test('requests carry the user JWT when signed in, nothing extra when guest', async () => {
  const guest = load();
  assert.equal(guest.ctx.sbHeaders().Authorization, undefined);
  assert.equal(guest.ctx.sbHeaders().apikey, 'sb_publishable_test');
  const user = load({ storage: loggedInStorage() });
  assert.equal(user.ctx.sbHeaders().Authorization, 'Bearer AT');
});

test('email sign-in sends the magic link request with the right redirect', async () => {
  const { ctx, calls } = load();
  await settle();
  await ctx.signInWithEmail('dana@example.com');
  const c = calls.find(x => x.url.includes('/auth/v1/otp'));
  assert.equal(c.method, 'POST');
  assert.ok(c.url.includes('redirect_to=https://user.github.io/lekanot/'));
  assert.deepEqual(JSON.parse(c.body), { email: 'dana@example.com', create_user: true });
});

test('Google sign-in redirects to the Supabase authorize endpoint and returns to this page', () => {
  const { ctx, win } = load();
  ctx.signInWithGoogle();
  assert.equal(win.location.href, 'https://proj.supabase.co/auth/v1/authorize?provider=google&redirect_to=' + encodeURIComponent('https://user.github.io/lekanot/'));
});

test('sign-out clears the session locally even if the server call fails', async () => {
  const { ctx, t, store } = load({ storage: loggedInStorage(), fetch: async (u) => { if (u.includes('/logout')) throw new Error('offline'); } });
  await settle();
  await ctx.signOut();
  assert.equal(t.auth.session, null);
  assert.equal(store.has('lekanot:auth'), false);
});

// ------------------------------------------------------------------ רשימות: מכשיר מול חשבון
test('guest: lists are saved on the device', async () => {
  const { ctx, store } = load();
  await ctx.listsSave({ name: 'שבת', category: 'שבת', items: [{ product_id: 'p1', qty: 2 }] });
  const saved = JSON.parse(store.get('lekanot:saved-lists'));
  assert.equal(saved.length, 1);
  const all = await ctx.listsAll();
  assert.equal(all[0].name, 'שבת');
  await ctx.listsRemove(all[0].id);
  assert.equal(JSON.parse(store.get('lekanot:saved-lists')).length, 0);
});

test('signed in: lists go to the account (user_lists), not to the device', async () => {
  const rows = [{ id: 'L1', name: 'פסח', category: 'פסח', items: [{ product_id: 'p1', qty: 1 }], created_at: '2026-01-01T00:00:00Z' }];
  const { ctx, calls, store } = load({ storage: loggedInStorage(), fetch: async (u, o) => (u.includes('/rest/v1/user_lists') && (o.method || 'GET') === 'GET' ? jsonRes(rows) : undefined) });
  await settle();
  const all = await ctx.listsAll();
  assert.equal(all[0].id, 'L1');
  assert.equal(all[0].remote, true);
  await ctx.listsSave({ name: 'חדשה', category: 'שבת', items: [] });
  const post = calls.find(c => c.method === 'POST' && c.url.includes('/rest/v1/user_lists'));
  assert.deepEqual(JSON.parse(post.body), { name: 'חדשה', category: 'שבת', items: [] }, 'user_id comes from the JWT via the column default - never sent by the client');
  assert.equal(store.get('lekanot:saved-lists'), undefined, 'nothing written to the device while signed in');
  await ctx.listsRemove('L1');
  assert.ok(calls.some(c => c.method === 'DELETE' && c.url.includes('id=eq.L1')));
});

test('on first sign-in, device lists move to the account exactly once (no duplicates)', async () => {
  const local = [{ id: 's_1', name: 'א', category: 'שבת', items: [], savedAt: 'x' }, { id: 's_2', name: 'ב', category: null, items: [], savedAt: 'x', synced: true }];
  const { ctx, calls, store } = load({ storage: loggedInStorage({ 'lekanot:saved-lists': local }) });
  await settle();
  const posts = () => calls.filter(c => c.method === 'POST' && c.url.includes('/rest/v1/user_lists?on_conflict=user_id,local_id'));
  const n0 = posts().length;
  assert.equal(n0, 1, 'one batched upsert on login');
  const body = JSON.parse(posts()[0].body);
  assert.deepEqual(body.map(b => b.local_id), ['s_1'], 'only the not-yet-synced list is uploaded');
  assert.match(posts()[0].headers.Prefer, /ignore-duplicates/);
  assert.ok(JSON.parse(store.get('lekanot:saved-lists')).every(l => l.synced));
  assert.equal(await ctx.syncLocalListsToAccount(), 0);
  assert.equal(posts().length, n0, 'second sync uploads nothing');
});

test('list names are escaped (no HTML injection)', async () => {
  const evil = [{ id: 's_1', name: '<img src=x onerror=alert(1)>', category: '"><b>', items: [], savedAt: '2026-01-01T00:00:00Z' }];
  const { ctx, els } = load({ storage: { 'lekanot:saved-lists': evil } });
  await ctx.renderListsPage();
  assert.ok(!els.listsContent.innerHTML.includes('<img src=x'), 'raw tag must not appear');
  assert.ok(els.listsContent.innerHTML.includes('&lt;img src=x'));
});

// ------------------------------------------------------------------ מיקום
test('haversine: Tel Aviv - Jerusalem is about 54 km', () => {
  const { ctx } = load();
  const km = ctx.haversineKm({ lat: 32.0853, lng: 34.7818 }, { lat: 31.7683, lng: 35.2137 });
  assert.ok(km > 51 && km < 57, String(km));
  assert.equal(ctx.haversineKm({ lat: 1, lng: 1 }, { lat: 1, lng: 1 }), 0);
});

test('active location follows the chosen mode and falls back to the other one', () => {
  const { ctx, t } = load();
  assert.equal(ctx.activeLocation(), null);
  t.loc.home = { lat: 32, lng: 34.8, label: 'בית' };
  assert.equal(ctx.activeLocation().label, 'בית');
  t.loc.mode = 'current';
  assert.equal(ctx.activeLocation().label, 'בית', 'no current location yet -> home');
  t.loc.current = { lat: 31, lng: 35, label: 'המיקום הנוכחי' };
  assert.equal(ctx.activeLocation().label, 'המיקום הנוכחי');
});

test('nearest store per chain, with distance text only when data exists', () => {
  const { ctx, t } = load();
  const stores = [
    { chain_id: 'A', name: 'א-קרוב', city: 'תל אביב', lat: 32.09, lng: 34.78 },
    { chain_id: 'A', name: 'א-רחוק', city: 'ירושלים', lat: 31.77, lng: 35.21 },
    { chain_id: 'B', name: 'ב', city: 'חיפה', lat: 32.79, lng: 34.99 },
  ];
  const nearest = ctx.nearestByChain({ lat: 32.0853, lng: 34.7818 }, stores);
  assert.equal(nearest.get('A').name, 'א-קרוב');
  assert.ok(nearest.get('B').km > 70);
  t.state.nearest = nearest;
  assert.match(ctx.nearestText('A'), /הסניף הקרוב: א-קרוב, תל אביב · 0\.\d ק״מ/);
  assert.match(ctx.nearestText('B'), /· \d{2} ק״מ/);
  assert.equal(ctx.nearestText('Z'), '', 'unknown chain: shows nothing, never an invented number');
  t.state.nearest = null;
  assert.equal(ctx.nearestText('A'), '');
});

test('no location set -> nothing is fetched or shown for distances', async () => {
  const { ctx, t, calls } = load();
  await ctx.prepareNearest();
  assert.equal(t.state.nearest, null);
  assert.ok(!calls.some(c => c.url.includes('/rest/v1/stores')));
});

test('location + geocoded stores -> distances prepared; stores without coordinates are never requested', async () => {
  const { ctx, t, calls } = load({ fetch: async (u) => (u.includes('/rest/v1/stores') ? jsonRes([{ chain_id: 'A', name: 'ס', city: 'ע', lat: 32.1, lng: 34.8 }]) : undefined) });
  t.loc.home = { lat: 32.0853, lng: 34.7818, label: 'בית' };
  await ctx.prepareNearest();
  assert.ok(t.state.nearest.get('A').km < 5);
  const q = calls.find(c => c.url.includes('/rest/v1/stores')).url;
  assert.ok(q.includes('lat=not.is.null') && q.includes('store_id_ext=neq.ALL'));
});

test('browser geolocation: success stores it, denial gives a clear message', async () => {
  const ok = load();
  ok.ctx.navigator.geolocation = { getCurrentPosition: (res) => res({ coords: { latitude: 32.1, longitude: 34.8 } }) };
  const cur = await ok.ctx.detectCurrentLocation();
  assert.equal(cur.lat, 32.1);
  assert.ok(ok.store.get('lekanot:location').includes('32.1'));
  const denied = load();
  denied.ctx.navigator.geolocation = { getCurrentPosition: (_r, rej) => rej({ code: 1 }) };
  await assert.rejects(denied.ctx.detectCurrentLocation(), /לא אושרה גישה/);
});

test('address search uses OpenStreetMap restricted to Israel, in Hebrew', async () => {
  const { ctx, calls } = load({ fetch: async (u) => (u.includes('nominatim') ? jsonRes([{ lat: '32.07', lon: '34.78', display_name: 'דיזנגוף 50, תל אביב-יפו, ישראל' }]) : undefined) });
  const p = await ctx.geocodeAddress('דיזנגוף 50 תל אביב');
  assert.equal(p.lat, 32.07);
  assert.equal(p.label, 'דיזנגוף 50, תל אביב-יפו');
  const url = calls.find(c => c.url.includes('nominatim')).url;
  assert.ok(url.includes('countrycodes=il') && url.includes('accept-language=he'));
});

test('home address is saved to the profile when signed in', async () => {
  const { ctx, calls } = load({ storage: loggedInStorage() });
  await settle();
  await ctx.setHome({ lat: 32.1, lng: 34.8, label: 'הבית' });
  const c = calls.find(x => x.method === 'POST' && x.url.includes('/rest/v1/profiles?on_conflict=id'));
  assert.ok(c, 'profile upsert');
  assert.deepEqual([JSON.parse(c.body)[0].id, JSON.parse(c.body)[0].home_lat], ['u1', 32.1]);
});

// ------------------------------------------------------------------ מנוע ההשוואה והמלאי (רגרסיה)
test('comparison ignores out-of-stock chains and groups by chain', async () => {
  const offers = [priceOffer('1', 'A', 'רשת א', 10, { carry: 3 }), priceOffer('2', 'B', 'רשת ב', 4, { in_stock: false, carry: 0 }), priceOffer('3', 'C', 'רשת ג', 8)];
  const { ctx } = load({ fetch: async (u) => (u.includes('/rest/v1/prices') ? jsonRes(offers) : undefined) });
  ctx.loadLinesIntoCart([{ product_id: 'milk', name: 'חלב', is_weighted: false, qty: 1, image_url: null }]);
  const plans = await ctx.computePlans();
  assert.equal(plans.single.chainName, 'רשת ג');
  assert.equal(plans.single.total, 8);
  assert.ok(!plans.allChains.some(c => c.chainName === 'רשת ב'));
});

test('single / split totals are computed at chain level', async () => {
  const prices = {
    milk: [priceOffer('1', 'A', 'א', 6), priceOffer('2', 'B', 'ב', 5)],
    bread: [priceOffer('3', 'A', 'א', 9)],
  };
  const { ctx } = load({ fetch: async (u) => { const m = decodeURIComponent(u).match(/product_id=eq\.(\w+)/); return m ? jsonRes(prices[m[1]] || []) : undefined; } });
  ctx.loadLinesIntoCart([{ product_id: 'milk', name: 'חלב', is_weighted: false, qty: 2, image_url: null }, { product_id: 'bread', name: 'לחם', is_weighted: false, qty: 1, image_url: null }]);
  const { single, splitUnlimited } = await ctx.computePlans();
  assert.equal(single.total, 21);
  assert.equal(splitUnlimited.total, 19);
  assert.equal(splitUnlimited.groups.length, 2);
});

test('search: context words stripped, exact product ranked before flavoured ones', () => {
  const { ctx } = load();
  assert.equal(ctx.extractCoreQuery('יין לקידוש'), 'יין');
  const r = ctx.rankProducts([{ canonical_name: 'חטיף דובון בטעם בננה' }, { canonical_name: 'בננה' }], 'בננה');
  assert.equal(r[0].canonical_name, 'בננה');
});

test('comparison list: chains that have EVERYTHING come first; a chain missing an item is not shown as "cheapest"', async () => {
  const prices = {
    milk: [priceOffer('1', 'A', 'א', 10), priceOffer('2', 'B', 'ב', 12), priceOffer('3', 'C', 'ג', 5)],
    oil: [priceOffer('4', 'A', 'א', 30), priceOffer('5', 'B', 'ב', 27)],   // רשת ג' לא מחזיקה שמן, ולכן זולה "בטעות"
  };
  const { ctx } = load({ fetch: async (u) => { const m = decodeURIComponent(u).match(/product_id=eq\.(\w+)/); return m ? jsonRes(prices[m[1]] || []) : undefined; } });
  ctx.loadLinesIntoCart([{ product_id: 'milk', name: 'חלב', is_weighted: false, qty: 1, image_url: null }, { product_id: 'oil', name: 'שמן', is_weighted: false, qty: 1, image_url: null }]);
  const { allChains } = await ctx.computePlans();
  assert.equal(JSON.stringify(allChains.map(c => [c.chainName, c.missing.length, c.total])), JSON.stringify([['ב', 0, 39], ['א', 0, 40], ['ג', 1, 5]]));
});
