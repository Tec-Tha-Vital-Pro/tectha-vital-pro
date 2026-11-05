// Voice assistant: the browser does speech-to-text and speaks replies (Web Speech API).
// Only text is sent to the server; no audio leaves this script.
(function () {
  "use strict";
  var root = document.getElementById("voice");
  if (!root) return;
  var mode = root.dataset.mode, csrf = root.dataset.csrf, token = null;
  var startForm = document.getElementById("v-start"), chat = document.getElementById("v-chat");
  var log = document.getElementById("v-log"), form = document.getElementById("v-form");
  var input = document.getElementById("v-text"), mic = document.getElementById("v-mic");
  var langSel = document.getElementById("v-lang"), errBox = document.getElementById("v-error");
  var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  var canSpeak = "speechSynthesis" in window;

  function lang() { return langSel.value || "en-IN"; }
  function showError(text) { errBox.textContent = text; errBox.hidden = !text; }
  function add(who, text) {
    var li = document.createElement("li");
    li.className = "v-" + who;
    li.textContent = text;
    log.appendChild(li);
    li.scrollIntoView({ block: "nearest" });
  }
  function speak(text) {
    if (!canSpeak) return;
    window.speechSynthesis.cancel();
    var u = new SpeechSynthesisUtterance(text);
    u.lang = lang();
    window.speechSynthesis.speak(u);
  }
  function post(url, body) {
    body.mode = mode;
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data.error || "Something went wrong. Please try again.");
        return data;
      });
    });
  }

  startForm.addEventListener("submit", function (e) {
    e.preventDefault();
    showError("");
    var phone = document.getElementById("v-phone");
    post("/voice/start", { consent: document.getElementById("v-consent").checked, lang: lang(),
                           phone: phone ? phone.value : "" })
      .then(function (data) {
        token = data.token;
        startForm.hidden = true;
        chat.hidden = false;
        add("bot", data.greeting);
        speak(data.greeting);
        if (!Rec) { document.getElementById("v-support").hidden = false; mic.hidden = true; }
      })
      .catch(function (err) { showError(err.message); });
  });

  function send(text) {
    text = (text || "").trim();
    if (!text || !token) return;
    showError("");
    add("me", text);
    input.value = "";
    post("/voice/turn", { token: token, text: text, lang: lang() })
      .then(function (data) { add("bot", data.reply); speak(data.reply); })
      .catch(function (err) { showError(err.message); });
  }

  form.addEventListener("submit", function (e) { e.preventDefault(); send(input.value); });

  if (Rec) {
    var rec = null;
    mic.addEventListener("click", function () {
      if (rec) { rec.stop(); return; }
      rec = new Rec();
      rec.lang = lang();
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      mic.setAttribute("aria-pressed", "true");
      mic.textContent = "● Listening… tap to stop";
      rec.onresult = function (ev) { send(ev.results[0][0].transcript); };
      rec.onerror = function (ev) {
        showError(ev.error === "not-allowed" ? "Allow the microphone for this site, or type instead."
                                             : "I couldn't hear that. Try again, or type instead.");
      };
      rec.onend = function () {
        rec = null;
        mic.setAttribute("aria-pressed", "false");
        mic.textContent = "Speak";
      };
      rec.start();
    });
  }
})();
