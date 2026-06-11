// Computes a step's frame_path: ordered selectors from the document down to the
// element's containing frame. Phase 1 handles shadow-DOM host chains (same
// document) and flags when an element lives in an iframe; full cross-origin
// iframe selector chains are deferred to Phase 3 (replay ignores frame_path for
// now, so an empty array is the safe default).

function computeFramePath(node) {
  const path = [];
  let root = node.getRootNode && node.getRootNode();
  // Walk up nested shadow roots, recording a selector for each shadow host.
  while (root && root.host) {
    const host = root.host;
    try {
      if (typeof createSelectorEngine === 'function' && window.__botaSelectorEngine) {
        path.unshift(window.__botaSelectorEngine.generateSelector(
          host, host.ownerDocument).primary);
      } else {
        path.unshift(host.tagName.toLowerCase());
      }
    } catch (e) { /* best effort */ }
    root = host.getRootNode && host.getRootNode();
  }
  return path;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { computeFramePath };
}
