// Service worker: makes the app installable and work offline.
// Strategy: cache the app shell; always try network first for menus.json
// so people see fresh menus, but fall back to cache if they're offline.

const CACHE = "dc-menus-v2";
const SHELL = ["./", "./index.html", "./manifest.json", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  // Menus: network-first (fresh data wins), fall back to cache offline.
  if (url.pathname.endsWith("menus.json")) {
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Everything else: cache-first.
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});

// Show a notification when a push arrives from the server
self.addEventListener("push", (e) => {
  let data = { title: "DC Menus", body: "One of your favorites is on the menu today!" };
  try { if (e.data) data = e.data.json(); } catch (_) {}
  e.waitUntil(
    self.registration.showNotification(data.title || "DC Menus", {
      body: data.body || "",
      icon: "icon-192.png",
      badge: "icon-192.png",
      data: { url: "./" },
    })
  );
});

// Focus/open the app when a notification is tapped
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({ type: "window" }).then((list) => {
      for (const c of list) if ("focus" in c) return c.focus();
      if (clients.openWindow) return clients.openWindow("./");
    })
  );
});
