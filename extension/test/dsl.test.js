// Tests the event-log -> Recipe DSL assembly (lib/dsl.js).
const assert = require('assert');
const { buildRecipe } = require('../lib/dsl.js');

let failures = 0;
function check(name, fn) {
  try { fn(); console.log('ok   ' + name); }
  catch (e) { failures++; console.error('FAIL ' + name + '\n  ' + e.message); }
}

check('first navigate kept, link navigations dropped', () => {
  const events = [
    { type: 'navigate', url: 'https://x.com', transition: 'start_page' },
    { type: 'click', selector: "a[href*='quote']", selector_fallbacks: [] },
    { type: 'navigate', url: 'https://x.com/quote', transition: 'link' },
    { type: 'type', selector: "input[name='email']", value: 'a@b.com' },
  ];
  const r = buildRecipe(events, { name: 't' });
  const types = r.steps.map(s => s.type);
  assert.deepStrictEqual(types, ['navigate', 'click', 'type']);
  assert.strictEqual(r.steps[0].url, 'https://x.com');
});

check('manual (typed) navigation in the middle is kept', () => {
  const events = [
    { type: 'navigate', url: 'https://a.com', transition: 'start_page' },
    { type: 'navigate', url: 'https://b.com', transition: 'typed' },
  ];
  const r = buildRecipe(events, {});
  assert.strictEqual(r.steps.length, 2);
  assert.strictEqual(r.steps[1].url, 'https://b.com');
});

check('duplicate consecutive click (submit+click) deduped', () => {
  const events = [
    { type: 'navigate', url: 'https://x.com', transition: 'start_page' },
    { type: 'click', selector: "button[type='submit']", selector_fallbacks: [] },
    { type: 'click', selector: "button[type='submit']", selector_fallbacks: [] },
  ];
  const r = buildRecipe(events, {});
  assert.strictEqual(r.steps.filter(s => s.type === 'click').length, 1);
});

check('sensitive value becomes a variable', () => {
  const events = [
    { type: 'navigate', url: 'https://x.com', transition: 'start_page' },
    { type: 'type', selector: "input[name='password']", value: null, sensitive: true, element_label: 'Password' },
  ];
  const r = buildRecipe(events, {});
  const typeStep = r.steps.find(s => s.type === 'type');
  assert.strictEqual(typeStep.value, '{{password}}');
  assert.strictEqual(r.variables.length, 1);
  assert.strictEqual(r.variables[0].name, 'password');
});

check('recipe carries source=extension and spec version', () => {
  const r = buildRecipe([{ type: 'navigate', url: 'https://x.com', transition: 'start_page' }],
    { selectorSpecVersion: 1 });
  assert.strictEqual(r.source, 'extension');
  assert.strictEqual(r.selector_spec_version, 1);
});

if (failures) { console.error(`\n${failures} dsl test(s) failed`); process.exit(1); }
console.log('\nall dsl tests passed');
