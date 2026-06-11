# Botasaurus Studio Recorder (Chrome extension)

Record interactions in your **own logged-in Chrome** — clicks, typing, selects,
form submits, navigations across pages and sites — and save them as replayable
[Botasaurus Automation Studio](../README.md) recipes. The point of the split:
you record as a real human (undetectable), and the studio replays the recipe in
Botasaurus's anti-detect Chrome.

## Install (unpacked, no Web Store)

1. Run the studio (`uvicorn backend.main:app --port 8000`) and open its
   **Settings** page — copy the **pairing token**.
2. In Chrome: `chrome://extensions` → enable **Developer mode** → **Load
   unpacked** → select this `extension/` folder.
3. Click the extension's **Studio connection settings** and paste the studio URL
   (`http://127.0.0.1:8000`) and the pairing token. Hit **Test connection**.

## Record a routine

1. Click the extension icon → **● Record**.
2. Do the thing — fill a form, click through pages, navigate to other sites.
3. **■ Stop**. Review the captured steps: delete any noise, edit values, or
   click **🔒 var** to turn a typed value into a `{{variable}}` (passwords and
   payment/OTP fields are auto-converted).
4. Name it and **Save to Studio**. Open the recipe in the studio to replay it
   (with different variable values), export it, or schedule it.

## How it stays correct

The selector engine (`content/selector.js`) is a line-for-line port of the
backend's `backend/agent/selectors.py`, both driven by
`shared/selector-spec.json`. Golden fixtures in `../tests/fixtures/selectors/`
are run through **both** engines (`npm test` here, `pytest
tests/test_selector_parity.py` in the backend) and must produce identical
output — so a recorded selector behaves the same way when the studio replays it.

## Develop / test

```bash
npm install      # jsdom, for the parity + dsl tests
npm test         # selector parity + DSL assembly
```

## What's captured

- `navigate` — first page load and any **manual** navigation (typed URL, reload).
  Link/form-submit navigations are implicit (the click reproduces them on replay).
- `type` — debounced into one step per field; password/OTP/cc fields flagged
  sensitive and turned into variables (never stored literally).
- `click` — links, buttons, checkboxes/radios, submit controls.
- `select_option` — dropdown changes (by value, with the label recorded).
- Each step also records healing hints (`element_label`, `element_text`, `tag`)
  so the studio's self-healing can relocate the element if the selector breaks.

Frames/shadow DOM: a `frame_path` is recorded for shadow-DOM hosts; full
cross-origin iframe replay is a later phase (the field is ignored on replay for
now).
