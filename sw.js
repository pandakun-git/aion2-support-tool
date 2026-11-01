/* v3.0 PWA shell. No game API or analytics interception. */
const CACHE='aion2-shell-v30';
const SHELL=['./','./index.html','./manifest.webmanifest','./icon.svg','./icon-180.png','./icon-192.png','./icon-512.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()).catch(()=>{}));});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('aion2-shell-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));});
self.addEventListener('fetch',e=>{const url=new URL(e.request.url);if(e.request.method!=='GET'||url.origin!==self.location.origin)return;
if(e.request.mode==='navigate')e.respondWith(fetch(e.request).then(r=>{if(r.ok){const copy=r.clone();caches.open(CACHE).then(c=>c.put('./index.html',copy)).catch(()=>{});}return r;}).catch(()=>caches.match('./index.html')));
else if(url.pathname.endsWith('/manifest.webmanifest')||url.pathname.endsWith('/icon.svg')||/\/icon-\d+\.png$/.test(url.pathname))e.respondWith(caches.match(e.request).then(cached=>cached||fetch(e.request)));
});
