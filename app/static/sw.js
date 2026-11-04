/* Tec Tha Vital service worker.
   Caches ONLY static assets (CSS, JS, icons, the offline page). Pages and anything with
   patient data always come from the network and are never stored on the device. */
const CACHE = "tectha-static-v2";
const ASSETS = ["/static/style.css", "/static/app.js", "/offline.html",
  "/static/icons/icon-192.png", "/static/icons/icon-512.png", "/static/icons/favicon-32.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === location.origin && url.pathname.startsWith("/static/")) {
    // Static files: cache first, refresh in the background.
    e.respondWith(caches.open(CACHE).then(async (c) => {
      const hit = await c.match(req);
      const net = fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  if (req.mode === "navigate") {
    // Pages: network only. Offline -> a static page with no patient data.
    e.respondWith(fetch(req).catch(() => caches.match("/offline.html")));
  }
});
