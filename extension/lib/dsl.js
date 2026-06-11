'use strict';

// Converts an arbitrary string into a safe snake_case variable name.
function slugify(str) {
  return String(str || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'value';
}

// Derives a variable name from an element label, avoiding names in `taken`.
function labelToVarName(label, taken) {
  const base = slugify(label) || 'value';
  let name = base;
  let n = 2;
  while (taken.has(name)) name = `${base}_${n++}`;
  return name;
}

// Derives a variable name from a CSS selector, avoiding names in `taken`.
// Exported for use in popup.js when the user clicks "🔒 var" on a type step.
function variableName(selector, taken) {
  taken = taken || new Set();
  let base = 'value';

  const nameAttr = /\[name=['"]?([^'"=\]]+)['"]?\]/.exec(selector);
  if (nameAttr) { base = slugify(nameAttr[1]); }
  else {
    const idHash = /^#([\w-]+)/.exec(selector);
    if (idHash) base = slugify(idHash[1]);
    else {
      const idAttr = /\[id=['"]?([^'"=\]]+)['"]?\]/.exec(selector);
      if (idAttr) base = slugify(idAttr[1]);
    }
  }

  let name = base;
  let n = 2;
  while (taken.has(name)) name = `${base}_${n++}`;
  return name;
}

// Navigate transitions caused by clicking a link — already represented by the
// preceding click step, so including them as an explicit navigate is redundant.
const LINK_TRANSITIONS = new Set(['link']);

/**
 * Converts a raw event log from the recorder into a clean recipe object.
 *
 * @param {Array}  events  - Raw events from chrome.storage.session
 * @param {Object} options - { name, botasaurus, selectorSpecVersion }
 * @returns {Object} recipe
 */
function buildRecipe(events, options) {
  options = options || {};
  const variables = [];
  const takenNames = new Set();
  const steps = [];

  for (let i = 0; i < events.length; i++) {
    const ev = events[i];

    if (ev.type === 'navigate') {
      if (LINK_TRANSITIONS.has(ev.transition)) continue;
      steps.push({ type: 'navigate', url: ev.url });
      continue;
    }

    if (ev.type === 'click') {
      // Deduplicate consecutive clicks on the same selector (e.g. double-fire
      // from a submit button triggering both a click and a form submit event).
      const prev = steps[steps.length - 1];
      if (prev && prev.type === 'click' && prev.selector === ev.selector) continue;
      const step = { type: 'click', selector: ev.selector };
      if (ev.selector_fallbacks && ev.selector_fallbacks.length) {
        step.selector_fallbacks = ev.selector_fallbacks;
      }
      steps.push(step);
      continue;
    }

    if (ev.type === 'type') {
      const step = { type: 'type', selector: ev.selector, value: ev.value };
      if (ev.sensitive) {
        const varName = labelToVarName(ev.element_label || ev.selector, takenNames);
        takenNames.add(varName);
        variables.push({ name: varName, default: '' });
        step.value = `{{${varName}}}`;
      }
      steps.push(step);
      continue;
    }

    // Pass through any other event types (scroll, select, hover, etc.)
    steps.push(Object.assign({}, ev));
  }

  return {
    name: options.name || 'Untitled',
    source: 'extension',
    selector_spec_version: options.selectorSpecVersion != null ? options.selectorSpecVersion : null,
    botasaurus: options.botasaurus || {},
    steps,
    variables,
  };
}

// Works as both an importScripts() global (service worker) and a CommonJS
// module (Node.js tests).
if (typeof module !== 'undefined') {
  module.exports = { buildRecipe, variableName };
}
