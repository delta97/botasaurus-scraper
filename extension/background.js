// Service worker: owns the recording session. MV3 workers are evicted when
// idle, so ALL state lives in chrome.storage.session (cleared on browser close)
// and is re-read on every wake — never kept only in worker globals.
//
// buildRecipe is inlined here because Chrome MV3 service workers do not
// reliably support importScripts(). The canonical source is lib/dsl.js
// (used by popup.html and the Node test suite).
'use strict';
(function () {
  function slugify(str) {
    return String(str || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'value';
  }
  function labelToVarName(label, taken) {
    const base = slugify(label) || 'value';
    let name = base, n = 2;
    while (taken.has(name)) name = `${base}_${n++}`;
    return name;
  }
  const LINK_TRANSITIONS = new Set(['link']);
  self.buildRecipe = function buildRecipe(events, options) {
    options = options || {};
    const variables = [], takenNames = new Set(), steps = [];
    for (const ev of events) {
      if (ev.type === 'navigate') {
        if (LINK_TRANSITIONS.has(ev.transition)) continue;
        steps.push({ type: 'navigate', url: ev.url });
      } else if (ev.type === 'click') {
        const prev = steps[steps.length - 1];
        if (prev && prev.type === 'click' && prev.selector === ev.selector) continue;
        const step = { type: 'click', selector: ev.selector };
        if (ev.selector_fallbacks && ev.selector_fallbacks.length) step.selector_fallbacks = ev.selector_fallbacks;
        steps.push(step);
      } else if (ev.type === 'type') {
        const step = { type: 'type', selector: ev.selector, value: ev.value };
        if (ev.sensitive) {
          const varName = labelToVarName(ev.element_label || ev.selector, takenNames);
          takenNames.add(varName);
          variables.push({ name: varName, default: '' });
          step.value = `{{${varName}}}`;
        }
        steps.push(step);
      } else {
        steps.push(Object.assign({}, ev));
      }
    }
    return {
      name: options.name || 'Untitled', source: 'extension',
      selector_spec_version: options.selectorSpecVersion != null ? options.selectorSpecVersion : null,
      botasaurus: options.botasaurus || {}, steps, variables,
    };
  };
})();

const CONTENT_FILES = ['content/selector.js', 'content/framepath.js', 'content/recorder.js'];

async function getState() {
  const { session } = await chrome.storage.session.get('session');
  return session || { recording: false, events: [], startedAt: null };
}
async function setState(state) {
  await chrome.storage.session.set({ session: state });
}
async function appendEvent(ev) {
  const state = await getState();
  if (!state.recording) return;
  state.events.push(ev);
  await setState(state);
}

async function injectInto(tabId) {
  try {
    await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: CONTENT_FILES });
  } catch (e) { /* chrome:// pages and the web store reject injection — ignore */ }
}

async function startRecording() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const events = [];
  if (tab && tab.url && /^https?:/.test(tab.url)) {
    events.push({ type: 'navigate', url: tab.url, transition: 'start_page' });
  }
  await setState({ recording: true, events, startedAt: Date.now(), tabId: tab ? tab.id : null });
  await chrome.action.setBadgeText({ text: 'REC' });
  await chrome.action.setBadgeBackgroundColor({ color: '#e05b5b' });
  if (tab) await injectInto(tab.id);
}

async function stopRecording() {
  const state = await getState();
  state.recording = false;
  await setState(state);
  await chrome.action.setBadgeText({ text: '' });
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.kind === 'bota-event') {
      await appendEvent({ ...msg.event, tabId: sender.tab ? sender.tab.id : null });
      sendResponse({ ok: true });
      return;
    }
    if (msg.kind === 'control') {
      if (msg.action === 'start') { await startRecording(); sendResponse({ ok: true }); return; }
      if (msg.action === 'stop') { await stopRecording(); sendResponse({ ok: true }); return; }
      if (msg.action === 'clear') { await setState({ recording: false, events: [], startedAt: null }); sendResponse({ ok: true }); return; }
      if (msg.action === 'status') {
        const s = await getState();
        sendResponse({ recording: s.recording, count: s.events.length, events: s.events });
        return;
      }
      if (msg.action === 'getRecipe') {
        const s = await getState();
        const recipe = buildRecipe(s.events, {
          name: msg.name, botasaurus: { headless: true, wait_for_complete_page_load: true },
          selectorSpecVersion: msg.selectorSpecVersion || null,
        });
        sendResponse({ recipe });
        return;
      }
    }
  })();
  return true;  // async sendResponse
});

// Capture navigations (full loads + SPA) and (re)inject the recorder.
chrome.webNavigation.onCommitted.addListener(async (details) => {
  const state = await getState();
  if (!state.recording) return;
  if (details.frameId === 0 && /^https?:/.test(details.url)) {
    await appendEvent({ type: 'navigate', url: details.url, transition: details.transitionType });
  }
  injectInto(details.tabId);
});

chrome.webNavigation.onHistoryStateUpdated.addListener(async (details) => {
  const state = await getState();
  if (!state.recording || details.frameId !== 0) return;
  await appendEvent({ type: 'navigate', url: details.url, transition: details.transitionType || 'link' });
});
