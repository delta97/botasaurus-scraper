// JS port of backend/agent/selectors.py. MUST produce identical output to the
// Python implementation for tests/fixtures/selectors/*.html (enforced by both
// tests/test_selector_parity.py and extension/test/selector.test.js).
//
// Constants come from extension/shared/selector-spec.json so the ladder and the
// unstable-id regex are single-sourced. Works as a content script (define
// createSelectorEngine in the isolated world) and under Node (module.exports).

function createSelectorEngine(spec) {
  const UNSTABLE_ID = new RegExp(spec.unstable_id_regex, spec.unstable_id_flags || '');
  const ATTRIBUTE_LADDER = spec.attribute_ladder;
  const HREF_MIN_SEGMENT = spec.href_min_segment_length;
  const INPUT_TYPE_SELF = new Set(spec.input_type_self_selectors);
  const MAX_FALLBACKS = spec.max_fallbacks;

  function cssEscape(value) {
    return String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
  }

  function looksStableId(value) {
    return Boolean(value) && !UNSTABLE_ID.test(value);
  }

  function attrCandidate(node, attr) {
    const value = node.getAttribute(attr);
    if (!value) return null;
    return `${node.tagName.toLowerCase()}[${attr}='${cssEscape(value)}']`;
  }

  function hrefCandidate(node) {
    const href = node.getAttribute('href');
    if (!href || href.startsWith('javascript:') || href.startsWith('#')) return null;
    const path = href.replace(/[?#].*$/, '').replace(/\/+$/, '');
    const segment = path.split('/').pop();
    if (segment && segment.length >= HREF_MIN_SEGMENT) {
      return `a[href*='${cssEscape(segment)}']`;
    }
    return `a[href='${cssEscape(href)}']`;
  }

  function nthPath(node) {
    const parts = [];
    let current = node;
    while (current && current.nodeType === 1) {
      const tagName = current.tagName.toLowerCase();
      if (tagName === 'html') break;
      const parent = current.parentElement;
      let anchor = null;
      const id = current.getAttribute('id');
      if (id && looksStableId(id)) anchor = '#' + cssEscape(id);
      let part;
      if (parent) {
        const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
        if (siblings.length > 1) {
          part = anchor || `${tagName}:nth-of-type(${siblings.indexOf(current) + 1})`;
        } else {
          part = anchor || tagName;
        }
      } else {
        part = anchor || tagName;
      }
      parts.push(part);
      if (anchor) break;
      if (tagName === 'body') break;
      current = parent;
    }
    return parts.reverse().join(' > ');
  }

  function isUnique(root, selector) {
    try {
      return root.querySelectorAll(selector).length === 1;
    } catch (e) {
      return false;
    }
  }

  function generateSelector(node, root) {
    root = root || node.ownerDocument || node;
    const tagName = node.tagName.toLowerCase();
    const candidates = [];

    const id = node.getAttribute('id');
    if (id && looksStableId(id)) candidates.push('#' + cssEscape(id));

    for (const attr of ATTRIBUTE_LADDER) {
      const cand = attrCandidate(node, attr);
      if (cand) candidates.push(cand);
    }

    if (tagName === 'a') {
      const cand = hrefCandidate(node);
      if (cand) candidates.push(cand);
    }

    if (tagName === 'input' && INPUT_TYPE_SELF.has(node.getAttribute('type'))) {
      candidates.push(`input[type='${node.getAttribute('type')}']`);
    }

    const unique = candidates.filter(c => isUnique(root, c));
    if (unique.length) {
      return { primary: unique[0], fallbacks: unique.slice(1, 1 + MAX_FALLBACKS), fragile: false };
    }
    return { primary: nthPath(node), fallbacks: candidates.slice(0, MAX_FALLBACKS), fragile: true };
  }

  return { generateSelector, cssEscape, looksStableId, specVersion: spec.selector_spec_version };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createSelectorEngine };
}
