/* Tec Tha Vital: small progressive enhancements. Every screen still works as plain forms. */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement;

  // Sidebar collapse (remembered on this device only).
  doc.addEventListener("click", function (e) {
    var t = e.target.closest("[data-side-toggle]");
    if (!t) {
      // Tablet: tapping outside the opened rail closes it.
      if (root.classList.contains("side-open") && !e.target.closest(".side")) root.classList.remove("side-open");
      return;
    }
    if (window.matchMedia("(max-width:980px)").matches) {   // tablet rail opens over the page
      var o = root.classList.toggle("side-open");
      t.setAttribute("aria-expanded", o ? "true" : "false");
      return;
    }
    var c = root.classList.toggle("side-collapsed");
    t.setAttribute("aria-label", c ? "Expand menu" : "Collapse menu");
    try { localStorage.setItem("tt-side", c ? "collapsed" : "open"); } catch (err) { /* private mode */ }
  });

  // Dialogs and slide-over panels: <button data-open="id">, <button data-close>.
  function openDialog(d) {
    if (!d || !d.showModal || d.open) return;
    d.showModal();
    var f = d.querySelector("[aria-invalid=true]") || d.querySelector("input:not([type=hidden]),select,textarea");
    if (f) f.focus();
  }
  doc.addEventListener("click", function (e) {
    var o = e.target.closest("[data-open]");
    if (o) { openDialog(doc.getElementById(o.getAttribute("data-open"))); return; }
    var c = e.target.closest("[data-close]");
    if (c) { var dl = c.closest("dialog"); if (dl) dl.close(); return; }
    if (e.target.tagName === "DIALOG") e.target.close();   // click on the backdrop
  });
  // A form that came back with an error reopens with what was typed (server marks it data-open-on-load).
  doc.querySelectorAll("dialog[data-open-on-load]").forEach(openDialog);

  // Toasts: success fades after its time (30 s when it offers Undo); errors stay until dismissed.
  doc.addEventListener("click", function (e) {
    var x = e.target.closest("[data-dismiss]");
    if (x) x.closest(".toast").remove();
  });
  doc.querySelectorAll(".toast[data-autohide]").forEach(function (t) {
    var ms = parseInt(t.getAttribute("data-autohide"), 10) || 5000;
    setTimeout(function () { t.classList.add("leaving"); setTimeout(function () { t.remove(); }, 300); }, ms);
  });
  // Drop ?msg / ?err from the address bar so a reload doesn't repeat the toast.
  if (/[?&](msg|err)=/.test(location.search) && history.replaceState) {
    var u = new URL(location.href); u.searchParams.delete("msg"); u.searchParams.delete("err");
    history.replaceState(null, "", u.pathname + (u.search || "") + u.hash);
  }

  // Selects that apply a filter or save immediately: ONLY when changed with a mouse or finger.
  // Arrow keys on a closed select change its value too (WCAG 3.2.2), so keyboard users press the
  // Save/Show button that appears when the control has focus.
  var lastPointer = false;
  doc.addEventListener("pointerdown", function () { lastPointer = true; }, true);
  doc.addEventListener("keydown", function () { lastPointer = false; }, true);
  doc.addEventListener("change", function (e) {
    var el = e.target;
    if (el.matches("[data-autosubmit]") && lastPointer && el.form) el.form.submit();
  });
  // Date field: never reload half-way through typing. Submit on Enter (native) or when focus leaves.
  doc.querySelectorAll("input[data-submit-on-blur]").forEach(function (inp) {
    var start = inp.value;
    inp.addEventListener("blur", function () { if (inp.value && inp.value !== start && inp.form) inp.form.submit(); });
  });

  // Account menu: close when clicking elsewhere, and on Esc (focus back on its button).
  doc.addEventListener("click", function (e) {
    doc.querySelectorAll("details.menu[open]").forEach(function (m) { if (!m.contains(e.target)) m.removeAttribute("open"); });
  });
  doc.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    root.classList.remove("side-open");
    doc.querySelectorAll("details.menu[open]").forEach(function (m) {
      m.removeAttribute("open"); var s = m.querySelector("summary"); if (s) s.focus();
    });
  });

  // Quick replies fill the reply box; staff still press Send.
  doc.addEventListener("click", function (e) {
    var q = e.target.closest("[data-fill]");
    if (!q) return;
    var box = doc.getElementById(q.getAttribute("data-target"));
    if (box) { box.value = q.getAttribute("data-fill"); box.focus(); }
  });

  // Keep the chat scrolled to the newest message.
  var thread = doc.querySelector("[data-thread]");
  if (thread) thread.scrollTop = thread.scrollHeight;

  // Live screens (Command Centre): reload every N seconds while visible; pause when the tab is hidden
  // or a dialog/menu is open, so nobody loses what they are doing.
  var live = doc.querySelector("[data-autorefresh]");
  if (live) {
    var every = (parseInt(live.getAttribute("data-autorefresh"), 10) || 30) * 1000;
    setInterval(function () {
      if (doc.hidden || doc.querySelector("dialog[open], details.menu[open]")) return;
      location.reload();
    }, every);
  }

  // Installable app: register the service worker (static files only).
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js").catch(function () {}); });
  }
})();
