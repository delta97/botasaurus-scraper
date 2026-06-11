const $ = (id) => document.getElementById(id);

chrome.storage.local.get(['studioUrl', 'pairingToken']).then(({ studioUrl, pairingToken }) => {
  $('studioUrl').value = studioUrl || 'http://127.0.0.1:8000';
  $('pairingToken').value = pairingToken || '';
});

$('saveBtn').onclick = async () => {
  await chrome.storage.local.set({
    studioUrl: $('studioUrl').value.trim(),
    pairingToken: $('pairingToken').value.trim(),
  });
  $('result').className = 'ok';
  $('result').textContent = 'Saved.';
};

$('testBtn').onclick = async () => {
  $('result').textContent = '';
  const url = $('studioUrl').value.trim().replace(/\/$/, '');
  try {
    const res = await fetch(url + '/api/extension/ping');
    const data = await res.json();
    $('result').className = 'ok';
    $('result').textContent = `Connected. API v${data.api_version}, selector spec v${data.selector_spec_version}.`;
  } catch (e) {
    $('result').className = 'err';
    $('result').textContent = 'Could not reach the studio: ' + e.message;
  }
};
