// Caches only static files. Pages with patient data are never cached.
const CACHE = 'tt-patient-v1';
const ASSETS = ['/static/patient.css', '/static/patient.js', '/static/icons/patient-192.png', '/static/icons/patient-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS))); self.skipWaiting(); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || !url.pathname.startsWith('/static/')) return;
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
});
