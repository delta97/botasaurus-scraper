// Injected into every page while recording. Captures clicks/typing/selects/
// submits, generates selectors via selector.js (parity with the Python
// backend), harvests healing hints, and streams events to the service worker.
(function () {
  if (window.__botaRecorderInstalled) return;
  window.__botaRecorderInstalled = true;

  let engine = null;
  const ready = (async () => {
    const spec = await (await fetch(chrome.runtime.getURL('shared/selector-spec.json'))).json();
    engine = createSelectorEngine(spec);     // defined in selector.js (same isolated world)
    window.__botaSelectorEngine = engine;
  })();

  const CLICKABLE = "a, button, [role='button'], input[type='submit'], input[type='button'], " +
    "input[type='checkbox'], input[type='radio'], input[type='image'], summary";
  const SENSITIVE_AUTOCOMPLETE = new Set(['cc-number', 'cc-csc', 'cc-exp', 'one-time-code', 'current-password', 'new-password']);

  function send(event) {
    try { chrome.runtime.sendMessage({ kind: 'bota-event', event }); } catch (e) { /* worker asleep; will wake */ }
  }

  // --- label / hint harvesting (mirrors backend snapshot._label_for order) ---
  function labelFor(node) {
    if (node.getAttribute('aria-label')) return node.getAttribute('aria-label');
    const id = node.getAttribute('id');
    if (id) {
      const lbl = document.querySelector(`label[for='${CSS.escape(id)}']`);
      if (lbl) return lbl.textContent.trim();
    }
    const wrap = node.closest && node.closest('label');
    if (wrap) return wrap.textContent.trim();
    if (node.getAttribute('placeholder')) return node.getAttribute('placeholder');
    if (node.tagName === 'INPUT' && ['submit', 'button'].includes(node.type) && node.value) return node.value;
    return null;
  }

  function isSensitive(node) {
    if (node.type === 'password') return true;
    const ac = (node.getAttribute('autocomplete') || '').toLowerCase();
    return SENSITIVE_AUTOCOMPLETE.has(ac);
  }

  function describe(node) {
    const sel = engine.generateSelector(node, document);
    return {
      selector: sel.primary,
      selector_fallbacks: sel.fallbacks,
      fragile: sel.fragile,
      frame_path: (typeof computeFramePath === 'function') ? computeFramePath(node) : [],
      element_label: labelFor(node),
      element_text: (node.textContent || '').trim().slice(0, 80) || null,
      tag: node.tagName.toLowerCase(),
      input_type: node.getAttribute && node.getAttribute('type'),
    };
  }

  // --- typing debounce: collapse consecutive input into one `type` step ------
  let pending = null;   // {node, descriptor, sensitive}
  function flushTyping() {
    if (!pending) return;
    const p = pending; pending = null;
    send({
      type: 'type',
      ...p.descriptor,
      value: p.sensitive ? null : p.node.value,
      sensitive: p.sensitive,
    });
  }

  document.addEventListener('input', (e) => {
    const node = e.target;
    if (!node || !('value' in node)) return;
    const editable = node.tagName === 'TEXTAREA' ||
      (node.tagName === 'INPUT' && !['checkbox', 'radio', 'submit', 'button', 'file'].includes(node.type)) ||
      node.isContentEditable;
    if (!editable) return;
    ready.then(() => {
      if (!pending || pending.node !== node) { flushTyping(); pending = { node, descriptor: describe(node), sensitive: isSensitive(node) }; }
    });
  }, true);

  document.addEventListener('keydown', (e) => { if (e.key === 'Enter') flushTyping(); }, true);

  document.addEventListener('click', (e) => {
    const target = e.target.closest ? e.target.closest(CLICKABLE) : null;
    ready.then(() => {
      flushTyping();
      if (!target) return;
      send({ type: 'click', ...describe(target) });
    });
  }, true);

  document.addEventListener('change', (e) => {
    const node = e.target;
    if (node.tagName !== 'SELECT') return;
    ready.then(() => {
      flushTyping();
      const opt = node.options[node.selectedIndex];
      send({ type: 'select_option', ...describe(node), value: node.value, label: opt ? opt.textContent.trim() : null });
    });
  }, true);

  document.addEventListener('submit', (e) => {
    const form = e.target;
    ready.then(() => {
      flushTyping();
      // If the user submitted via Enter (no submit-button click captured),
      // emit a click on the form's submit control so replay can reproduce it.
      const btn = form.querySelector("[type='submit'], button:not([type])");
      if (btn) send({ type: 'click', ...describe(btn) });
    });
  }, true);

  // Flush a half-typed field if the page is about to unload/navigate.
  window.addEventListener('beforeunload', flushTyping, true);
  window.addEventListener('pagehide', flushTyping, true);
})();
