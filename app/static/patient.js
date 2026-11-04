// Patient app: prevent double taps on forms and register the service worker (static assets only).
document.addEventListener('submit', function (e) {
  var f = e.target;
  if (!f.hasAttribute('data-once')) return;
  if (f.dataset.sent) { e.preventDefault(); return; }
  f.dataset.sent = '1';
  setTimeout(function () { f.querySelectorAll('button').forEach(function (b) { b.disabled = true; }); }, 0);
});
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/my/sw.js', { scope: '/my/' }).catch(function (err) {
      console.warn('Service worker not registered:', err);
    });
  });
}
