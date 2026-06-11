// Computes a step's frame_path: ordered selectors from the document down to the
// element's containing frame. Phase 1 handles shadow-DOM host chains (same
// document) and flags when an element lives in an iframe; full cross-origin
// iframe selector chains are deferred to Phase 3 (replay ignores frame_path for
// now, so an empty array is the safe default).

function computeFramePath(node) {
  const path = [];
  const engine = window.__botaSelectorEngine;
  const selectorFor = (el, doc) => {
    try { if (engine) return engine.generateSelector(el, doc).primary; } catch (e) { /* fall through */ }
    return el.tagName.toLowerCase();
  };

  // 1. Nested shadow roots: a selector for each shadow host, innermost last.
  let root = node.getRootNode && node.getRootNode();
  while (root && root.host) {
    const host = root.host;
    path.unshift(selectorFor(host, host.ownerDocument));
    root = host.getRootNode && host.getRootNode();
  }

  // 2. Same-origin iframe chain: a selector for each iframe element in its
  // parent document, outermost first. Cross-origin parents throw — stop there
  // (the replay engine can only reach same-origin frames by selector anyway).
  try {
    let win = node.ownerDocument && node.ownerDocument.defaultView;
    while (win && win.frameElement) {
      const frameEl = win.frameElement;
      path.unshift(selectorFor(frameEl, frameEl.ownerDocument));
      win = win.parent;
    }
  } catch (e) { /* cross-origin boundary reached */ }

  return path;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { computeFramePath };
}
