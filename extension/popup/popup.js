const $ = (id) => document.getElementById(id);
let recipe = null;   // local editable copy after Stop

function control(action, extra = {}) {
  return chrome.runtime.sendMessage({ kind: 'control', action, ...extra });
}

async function refresh() {
  const status = await control('status');
  const recording = status && status.recording;
  $('status').textContent = recording ? 'recording' : 'idle';
  $('status').className = 'status' + (recording ? ' rec' : '');
  $('recordBtn').hidden = recording;
  $('stopBtn').hidden = !recording;
  const count = status ? status.events.length : 0;
  $('clearBtn').hidden = recording || count === 0;
  $('liveCount').hidden = !recording;
  if (recording) $('liveCount').textContent = `${count} events captured…`;

  if (!recording && count > 0) {
    const res = await control('getRecipe', { name: $('recipeName').value || 'recorded-flow' });
    recipe = res.recipe;
    renderReview();
    $('review').hidden = false;
  } else {
    $('review').hidden = true;
  }
}

function renderReview() {
  const wrap = $('steps');
  wrap.innerHTML = '';
  recipe.steps.forEach((step, i) => {
    const div = document.createElement('div');
    div.className = 'step';
    const head = document.createElement('div');
    head.className = 'step-head';
    head.innerHTML = `<span class="t">${step.type}</span>` +
      `<span class="sel">${step.url || step.selector || ''}</span>`;
    if (step.type === 'type' && typeof step.value === 'string' && !/^\{\{/.test(step.value)) {
      const varBtn = document.createElement('button');
      varBtn.className = 'var'; varBtn.textContent = '🔒 var';
      varBtn.onclick = () => makeVariable(i);
      head.appendChild(varBtn);
    }
    const x = document.createElement('button');
    x.className = 'x'; x.textContent = '✕';
    x.onclick = () => { recipe.steps.splice(i, 1); renderReview(); };
    head.appendChild(x);
    div.appendChild(head);
    if ('value' in step && step.value !== null && step.value !== undefined) {
      const inp = document.createElement('input');
      inp.className = 'val'; inp.value = step.value;
      inp.oninput = () => { step.value = inp.value; };
      div.appendChild(inp);
    }
    wrap.appendChild(div);
  });
}

function makeVariable(i) {
  const step = recipe.steps[i];
  const taken = new Set((recipe.variables || []).map(v => v.name));
  const name = variableName(step.selector, taken);   // from lib/dsl.js
  recipe.variables = recipe.variables || [];
  recipe.variables.push({ name, default: step.value || '' });
  step.value = `{{${name}}}`;
  renderReview();
}

async function save() {
  $('saveResult').textContent = '';
  const { studioUrl, pairingToken } = await chrome.storage.local.get(['studioUrl', 'pairingToken']);
  if (!studioUrl || !pairingToken) {
    $('saveResult').className = 'err';
    $('saveResult').textContent = 'Set the studio URL + token in connection settings first.';
    return;
  }
  recipe.name = $('recipeName').value || 'recorded-flow';
  try {
    const res = await fetch(studioUrl.replace(/\/$/, '') + '/api/recipes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Studio-Token': pairingToken },
      body: JSON.stringify({ name: recipe.name, description: recipe.description, definition: recipe }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    $('saveResult').className = 'ok';
    $('saveResult').innerHTML = `Saved as recipe #${data.recipe_id}` +
      (data.warning ? `<br><span class="err">${data.warning}</span>` : '');
    await control('clear');
  } catch (e) {
    $('saveResult').className = 'err';
    $('saveResult').textContent = 'Save failed: ' + e.message;
  }
}

$('recordBtn').onclick = async () => { await control('start'); refresh(); };
$('stopBtn').onclick = async () => { await control('stop'); refresh(); };
$('clearBtn').onclick = async () => { await control('clear'); refresh(); };
$('saveBtn').onclick = save;
$('optionsLink').onclick = (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); };
refresh();
