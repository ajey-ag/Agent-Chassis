/* Minimal PWA service worker: cache the static shell, never cache the API
   (stale approval queues would be actively dangerous). */
const CACHE = "chassis-v1";
const SHELL = ["/", "/static/style.css", "/static/app.js", "/static/manifest.json", "/static/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/ws")) return; // network only
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});
