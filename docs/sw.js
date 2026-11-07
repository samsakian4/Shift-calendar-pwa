// Service worker: پوسته‌ی برنامه را آفلاین نگه می‌دارد. داده‌ها (Supabase) هرگز کش نمی‌شوند.
// بعد از هر تغییر در فایل‌ها، شماره‌ی VERSION را زیاد کنید.
const VERSION = 'shiftcal-v5';
const SHELL = [
  './', 'index.html', 'config.js', 'manifest.webmanifest', 'vendor/supabase.js',
  'vendor/fonts/vazirmatn-arabic-400-normal.woff2', 'vendor/fonts/vazirmatn-arabic-500-normal.woff2',
  'vendor/fonts/vazirmatn-arabic-700-normal.woff2', 'vendor/fonts/vazirmatn-latin-400-normal.woff2',
  'vendor/fonts/vazirmatn-latin-500-normal.woff2', 'vendor/fonts/vazirmatn-latin-700-normal.woff2',
  'vendor/fonts/lalezar-arabic-400-normal.woff2',
  'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-maskable-512.png', 'icons/favicon-32.png', 'icons/apple-touch-icon.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return; // Supabase و بقیه‌ی درخواست‌های بیرونی دست‌نخورده
  const staticAsset = /\/(vendor|icons)\//.test(url.pathname);
  if (staticAsset) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); return res;
    })));
    return;
  }
  // صفحه و تنظیمات: اول شبکه (نسخه‌ی تازه)، در صورت قطعی از کش
  e.respondWith(
    fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req).then((hit) => hit || (req.mode === 'navigate' ? caches.match('index.html') : undefined)))
  );
});
