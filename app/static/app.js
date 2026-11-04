/* Tec Tha Care Connect: small progressive enhancements. Every screen still works as plain forms. */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement;

  // Sidebar collapse (remembered on this device only).
  doc.addEventListener("click", function (e) {
    var t = e.target.closest("[data-side-toggle]");
    if (!t) return;
    var c = root.classList.toggle("side-collapsed");
    t.setAttribute("aria-label", c ? "Expand menu" : "Collapse menu");
    try { localStorage.setItem("tt-side", c ? "collapsed" : "open"); } catch (err) { /* private mode */ }
  });

  // Dialogs and slide-over panels: <button data-open="id">, <button data-close>.
  doc.addEventListener("click", function (e) {
    var o = e.target.closest("[data-open]");
    if (o) {
      var d = doc.getElementById(o.getAttribute("data-open"));
      if (d && d.showModal) { d.showModal(); var f = d.querySelector("input:not([type=hidden]),select,textarea"); if (f) f.focus(); }
      return;
    }
    var c = e.target.closest("[data-close]");
    if (c) { var dl = c.closest("dialog"); if (dl) dl.close(); return; }
    // Click on the backdrop closes a dialog.
    if (e.target.tagName === "DIALOG") e.target.close();
  });

  // Toasts: success messages fade out; errors stay until dismissed.
  doc.addEventListener("click", function (e) {
    var x = e.target.closest("[data-dismiss]");
    if (x) x.closest(".toast").remove();
  });
  doc.querySelectorAll(".toast[data-autohide]").forEach(function (t) {
    setTimeout(function () { t.classList.add("leaving"); setTimeout(function () { t.remove(); }, 300); }, 5000);
  });
  // Drop ?msg / ?err from the address bar so a reload doesn't repeat the toast.
  if (/[?&](msg|err)=/.test(location.search) && history.replaceState) {
    var u = new URL(location.href); u.searchParams.delete("msg"); u.searchParams.delete("err");
    history.replaceState(null, "", u.pathname + (u.search || "") + u.hash);
  }

  // Selects that apply a filter immediately.
  doc.addEventListener("change", function (e) {
    if (e.target.matches("[data-autosubmit]")) e.target.form.submit();
  });

  // Close the account menu when clicking elsewhere.
  doc.addEventListener("click", function (e) {
    doc.querySelectorAll("details.menu[open]").forEach(function (m) { if (!m.contains(e.target)) m.removeAttribute("open"); });
  });

  // Keep the chat scrolled to the newest message.
  var thread = doc.querySelector("[data-thread]");
  if (thread) thread.scrollTop = thread.scrollHeight;

  // Installable app: register the service worker (static files only).
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js").catch(function () {}); });
  }
})();
