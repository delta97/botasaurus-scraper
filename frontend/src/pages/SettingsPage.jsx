import { useEffect, useState } from 'react'
import { api } from '../api'
import BotasaurusConfigForm from '../components/BotasaurusConfigForm'

export default function SettingsPage() {
  const [settings, setSettings] = useState(null)
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [config, setConfig] = useState({})
  const [models, setModels] = useState([])
  const [filter, setFilter] = useState('')
  const [status, setStatus] = useState(null)
  const [webhook, setWebhook] = useState('')

  useEffect(() => {
    api('/api/settings').then((s) => {
      setSettings(s)
      setModel(s.openrouter_model)
      setConfig(s.default_botasaurus_config)
      setWebhook(s.notify_webhook_url || '')
    }).catch((e) => setStatus({ error: e.message }))
    api('/api/models').then((d) => setModels(d.models)).catch(() => setModels([]))
  }, [])

  const regenerateToken = async () => {
    try {
      const r = await api('/api/settings/regenerate-pairing-token', { method: 'POST' })
      setSettings({ ...settings, extension_pairing_token: r.extension_pairing_token })
      setStatus({ ok: 'New pairing token generated — update it in the extension.' })
    } catch (e) { setStatus({ error: e.message }) }
  }

  const save = async () => {
    setStatus(null)
    try {
      const payload = {
        openrouter_model: model,
        default_botasaurus_config: config,
        notify_webhook_url: webhook,
      }
      if (apiKey) payload.openrouter_api_key = apiKey
      const updated = await api('/api/settings', { method: 'PUT', body: payload })
      setSettings(updated)
      setApiKey('')
      setStatus({ ok: 'Settings saved.' })
    } catch (e) {
      setStatus({ error: e.message })
    }
  }

  if (!settings) return <p className="muted">Loading…</p>
  const filtered = filter
    ? models.filter((m) => (m.id + m.name).toLowerCase().includes(filter.toLowerCase()))
    : models

  return (
    <div>
      <h2>Settings</h2>
      {status?.error && <div className="error-banner">{status.error}</div>}
      {status?.ok && <div className="success-banner">{status.ok}</div>}

      <div className="card">
        <h3>OpenRouter</h3>
        <label className="field">
          <span>
            API key{' '}
            {settings.openrouter_api_key_set
              ? `(currently set: ${settings.openrouter_api_key_preview} — enter a new key to replace)`
              : '(not set — required to run AI tasks)'}
          </span>
          <input
            type="password"
            value={apiKey}
            placeholder="sk-or-v1-..."
            onChange={(e) => setApiKey(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Filter models</span>
          <input type="text" value={filter} placeholder="e.g. claude, gpt, free"
                 onChange={(e) => setFilter(e.target.value)} />
        </label>
        <label className="field">
          <span>Model ({filtered.length} available)</span>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {!filtered.some((m) => m.id === model) && model && (
              <option value={model}>{model}</option>
            )}
            {filtered.slice(0, 100).map((m) => (
              <option key={m.id} value={m.id}>{m.id}</option>
            ))}
          </select>
        </label>
        <p className="muted">
          The key is stored obfuscated (not encrypted) in the local SQLite database
          and is never returned by the API.
        </p>
      </div>

      <div className="card">
        <h3>Chrome extension recorder</h3>
        <p className="muted">
          Install the <code>extension/</code> folder unpacked in Chrome
          (chrome://extensions → Developer mode → Load unpacked), then paste this
          pairing token into the extension's connection settings. It authorizes
          the extension to save recorded recipes to this studio.
        </p>
        <label className="field">
          <span>Pairing token</span>
          <input type="text" readOnly value={settings.extension_pairing_token || ''}
                 onFocus={(e) => e.target.select()} />
        </label>
        <button className="secondary small" onClick={regenerateToken}>Regenerate token</button>
      </div>

      <div className="card">
        <h3>Notifications</h3>
        <label className="field">
          <span>Failure webhook URL (Slack/Discord-compatible, optional)</span>
          <input type="text" value={webhook} placeholder="https://hooks.slack.com/services/..."
                 onChange={(e) => setWebhook(e.target.value)} />
        </label>
        <p className="muted">A JSON summary is POSTed here when a scheduled or batch run fails.</p>
      </div>

      <div className="card">
        <h3>Default Botasaurus configuration</h3>
        <p className="muted">Used for new tasks unless overridden per run.</p>
        <BotasaurusConfigForm value={config} onChange={setConfig} />
      </div>

      <button onClick={save}>Save settings</button>
    </div>
  )
}
