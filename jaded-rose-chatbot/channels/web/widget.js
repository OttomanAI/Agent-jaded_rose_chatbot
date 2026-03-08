/**
 * Jaded Rose — Embeddable Chat Widget
 *
 * Vanilla JS widget that opens as a floating button in the bottom-right
 * corner of the page.  Communicates with the backend via a WebSocket
 * connection at /ws/chat.  Stores message history in sessionStorage so
 * conversations survive page navigations within the same tab.
 *
 * Drop a single <script src="/static/widget.js"></script> into any page
 * (or a Shopify theme) to activate the widget.
 */

(function () {
  "use strict";

  /* ── Configuration ──────────────────────────────────────────────── */
  var WS_URL =
    (location.protocol === "https:" ? "wss://" : "ws://") +
    location.host +
    "/ws/chat";
  var STORAGE_KEY = "jr_chat_history";
  var SESSION_KEY = "jr_session_id";

  /* ── State ──────────────────────────────────────────────────────── */
  var ws = null;
  var isOpen = false;
  var sessionId = sessionStorage.getItem(SESSION_KEY) || null;

  /* ── Helpers ────────────────────────────────────────────────────── */

  function saveHistory(messages) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch (_) {}
  }

  function loadHistory() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (_) {
      return [];
    }
  }

  /* ── Inject Styles ──────────────────────────────────────────────── */

  function injectStyles() {
    var css = [
      "#jr-chat-fab{",
      "  position:fixed;bottom:24px;right:24px;z-index:99999;",
      "  width:60px;height:60px;border-radius:50%;border:none;",
      "  background:#1a1a1a;color:#fff;cursor:pointer;",
      "  box-shadow:0 4px 14px rgba(0,0,0,.25);",
      "  font-size:28px;display:flex;align-items:center;justify-content:center;",
      "  transition:transform .2s;",
      "}",
      "#jr-chat-fab:hover{transform:scale(1.08);}",
      "#jr-chat-panel{",
      "  position:fixed;bottom:100px;right:24px;z-index:99999;",
      "  width:380px;max-width:calc(100vw - 32px);height:520px;max-height:calc(100vh - 140px);",
      "  background:#1a1a1a;border-radius:16px;overflow:hidden;",
      "  display:none;flex-direction:column;",
      "  box-shadow:0 8px 30px rgba(0,0,0,.35);font-family:'Helvetica Neue',Arial,sans-serif;",
      "}",
      "#jr-chat-panel.open{display:flex;}",
      "#jr-chat-header{",
      "  padding:16px 20px;background:#111;color:#fff;",
      "  display:flex;align-items:center;justify-content:space-between;",
      "}",
      "#jr-chat-header h3{margin:0;font-size:16px;font-weight:600;letter-spacing:.3px;}",
      "#jr-chat-close{background:none;border:none;color:#888;font-size:22px;cursor:pointer;}",
      "#jr-chat-messages{",
      "  flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;",
      "}",
      ".jr-msg{max-width:82%;padding:10px 14px;border-radius:14px;font-size:14px;line-height:1.45;word-wrap:break-word;}",
      ".jr-msg.user{align-self:flex-end;background:#333;color:#fff;border-bottom-right-radius:4px;}",
      ".jr-msg.bot{align-self:flex-start;background:#2a2a2a;color:#ddd;border-bottom-left-radius:4px;}",
      ".jr-typing{align-self:flex-start;padding:10px 14px;display:none;}",
      ".jr-typing span{display:inline-block;width:8px;height:8px;margin:0 2px;background:#555;border-radius:50%;animation:jr-bounce 1.3s infinite ease-in-out;}",
      ".jr-typing span:nth-child(2){animation-delay:.15s;}",
      ".jr-typing span:nth-child(3){animation-delay:.3s;}",
      "@keyframes jr-bounce{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-8px)}}",
      "#jr-chat-input-row{",
      "  display:flex;padding:12px;background:#111;gap:8px;",
      "}",
      "#jr-chat-input{",
      "  flex:1;border:1px solid #333;border-radius:10px;padding:10px 14px;",
      "  background:#1a1a1a;color:#fff;font-size:14px;outline:none;resize:none;",
      "  font-family:inherit;",
      "}",
      "#jr-chat-input::placeholder{color:#666;}",
      "#jr-chat-send{",
      "  border:none;background:#fff;color:#1a1a1a;border-radius:10px;",
      "  padding:0 18px;font-size:15px;font-weight:600;cursor:pointer;",
      "}",
      "#jr-chat-send:hover{background:#e0e0e0;}",
      "@media(max-width:480px){",
      "  #jr-chat-panel{width:calc(100vw - 16px);right:8px;bottom:90px;height:calc(100vh - 120px);border-radius:12px;}",
      "  #jr-chat-fab{width:52px;height:52px;font-size:24px;bottom:16px;right:16px;}",
      "}",
    ].join("\n");

    var style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);
  }

  /* ── Build DOM ──────────────────────────────────────────────────── */

  function buildUI() {
    // FAB
    var fab = document.createElement("button");
    fab.id = "jr-chat-fab";
    fab.innerHTML = "💬";
    fab.setAttribute("aria-label", "Open chat");
    fab.addEventListener("click", togglePanel);

    // Panel
    var panel = document.createElement("div");
    panel.id = "jr-chat-panel";
    panel.innerHTML = [
      '<div id="jr-chat-header">',
      '  <h3>✨ Jaded Rose</h3>',
      '  <button id="jr-chat-close">&times;</button>',
      "</div>",
      '<div id="jr-chat-messages">',
      '  <div class="jr-msg bot">Hey! 👋 Welcome to Jaded Rose. How can I help you today?</div>',
      '  <div class="jr-typing"><span></span><span></span><span></span></div>',
      "</div>",
      '<div id="jr-chat-input-row">',
      '  <textarea id="jr-chat-input" placeholder="Type a message…" rows="1"></textarea>',
      '  <button id="jr-chat-send">Send</button>',
      "</div>",
    ].join("\n");

    document.body.appendChild(fab);
    document.body.appendChild(panel);

    document.getElementById("jr-chat-close").addEventListener("click", togglePanel);
    document.getElementById("jr-chat-send").addEventListener("click", sendMessage);
    document.getElementById("jr-chat-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    // Restore history
    var history = loadHistory();
    if (history.length) {
      var container = document.getElementById("jr-chat-messages");
      // Remove the default welcome bubble when restoring
      var firstChild = container.querySelector(".jr-msg.bot");
      if (firstChild) firstChild.remove();
      history.forEach(function (m) {
        appendBubble(m.role, m.text, true);
      });
    }
  }

  /* ── Panel toggle ───────────────────────────────────────────────── */

  function togglePanel() {
    var panel = document.getElementById("jr-chat-panel");
    isOpen = !isOpen;
    panel.classList.toggle("open", isOpen);
    if (isOpen) {
      connectWS();
      document.getElementById("jr-chat-input").focus();
      scrollToBottom();
    }
  }

  /* ── WebSocket ──────────────────────────────────────────────────── */

  function connectWS() {
    if (ws && ws.readyState <= 1) return; // CONNECTING or OPEN
    ws = new WebSocket(WS_URL);

    ws.onmessage = function (event) {
      var data = JSON.parse(event.data);

      if (data.session_id) {
        sessionId = data.session_id;
        sessionStorage.setItem(SESSION_KEY, sessionId);
      }

      if (data.typing === true) {
        showTyping(true);
        return;
      }

      showTyping(false);

      if (data.reply) {
        appendBubble("bot", data.reply);
      }
    };

    ws.onclose = function () {
      // Auto-reconnect after a short delay
      setTimeout(connectWS, 2000);
    };
  }

  /* ── Messages ───────────────────────────────────────────────────── */

  function appendBubble(role, text, skipSave) {
    var container = document.getElementById("jr-chat-messages");
    var div = document.createElement("div");
    div.className = "jr-msg " + role;
    div.textContent = text;

    // Insert before the typing indicator
    var typing = container.querySelector(".jr-typing");
    container.insertBefore(div, typing);
    scrollToBottom();

    if (!skipSave) {
      var history = loadHistory();
      history.push({ role: role, text: text });
      saveHistory(history);
    }
  }

  function showTyping(visible) {
    var el = document.querySelector(".jr-typing");
    if (el) el.style.display = visible ? "flex" : "none";
    if (visible) scrollToBottom();
  }

  function scrollToBottom() {
    var container = document.getElementById("jr-chat-messages");
    if (container) container.scrollTop = container.scrollHeight;
  }

  function sendMessage() {
    var input = document.getElementById("jr-chat-input");
    var text = input.value.trim();
    if (!text) return;

    appendBubble("user", text);
    input.value = "";

    if (!ws || ws.readyState !== 1) {
      connectWS();
      appendBubble("bot", "Reconnecting… please try again in a moment.");
      return;
    }

    ws.send(JSON.stringify({ message: text, session_id: sessionId }));
  }

  /* ── Initialise ─────────────────────────────────────────────────── */

  function init() {
    injectStyles();
    buildUI();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
