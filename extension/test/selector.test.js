// Node half of the selector parity check. Runs extension/content/selector.js
// over the SAME golden fixtures as tests/test_selector_parity.py and asserts
// the SAME tests/fixtures/selectors/cases.json. Exit non-zero on any mismatch.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { JSDOM } = require('jsdom');

const { createSelectorEngine } = require('../content/selector.js');
const spec = require('../shared/selector-spec.json');

const FIXTURE_DIR = path.resolve(__dirname, '../../tests/fixtures/selectors');
const cases = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, 'cases.json'), 'utf8'));

const engine = createSelectorEngine(spec);

assert.strictEqual(cases.selector_spec_version, spec.selector_spec_version,
  'cases.json spec version != selector-spec.json');

let failures = 0;
for (const c of cases.cases) {
  const html = fs.readFileSync(path.join(FIXTURE_DIR, c.file), 'utf8');
  const dom = new JSDOM(html);
  const node = dom.window.document.querySelector('[data-fixture-target]');
  if (!node) { console.error(`${c.file}: no [data-fixture-target]`); failures++; continue; }
  const got = engine.generateSelector(node, dom.window.document);
  try {
    assert.deepStrictEqual(got, c.expected);
    console.log(`ok   ${c.file}  -> ${got.primary}`);
  } catch (e) {
    failures++;
    console.error(`FAIL ${c.file}`);
    console.error(`  got:      ${JSON.stringify(got)}`);
    console.error(`  expected: ${JSON.stringify(c.expected)}`);
  }
}

if (failures) {
  console.error(`\n${failures} selector parity mismatch(es)`);
  process.exit(1);
}
console.log(`\nall ${cases.cases.length} selector parity cases passed`);
