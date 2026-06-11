import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import BotasaurusConfigForm from '../components/BotasaurusConfigForm'

export default function NewTaskPage() {
  const navigate = useNavigate()
  const [goal, setGoal] = useState('')
  const [url, setUrl] = useState('')
  const [config, setConfig] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [keySet, setKeySet] = useState(true)

  useEffect(() => {
    api('/api/settings').then((s) => {
      setConfig(s.default_botasaurus_config)
      setKeySet(s.openrouter_api_key_set)
    }).catch((e) => setError(e.message))
  }, [])

  const start = async () => {
    setError(null)
    setBusy(true)
    try {
      const { run_id } = await api('/api/runs', {
        method: 'POST',
        body: { goal, start_url: normalizeUrl(url), botasaurus_config: config },
      })
      navigate(`/runs/${run_id}`)
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }

  return (
    <div>
      <h2>New Task</h2>
      {!keySet && (
        <div className="error-banner">
          No OpenRouter API key configured — set one in Settings before running AI tasks.
        </div>
      )}
      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <label className="field">
          <span>What should the agent do? (natural language)</span>
          <textarea
            value={goal}
            placeholder={'e.g. "Fill out the lead form with name John Smith, email john@example.com, ZIP 94107 and submit it" or "Extract the article as markdown"'}
            onChange={(e) => setGoal(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Starting web address</span>
          <input
            type="text"
            value={url}
            placeholder="https://modernize.com"
            onChange={(e) => setUrl(e.target.value)}
          />
        </label>
      </div>

      {config && (
        <div className="card">
          <details className="collapse" open={false}>
            <summary>Botasaurus browser configuration</summary>
            <div style={{ marginTop: '0.8rem' }}>
              <BotasaurusConfigForm value={config} onChange={setConfig} />
            </div>
          </details>
        </div>
      )}

      <button onClick={start} disabled={busy || goal.length < 3 || url.length < 4}>
        {busy ? 'Starting…' : '▶ Run task'}
      </button>
      <p className="muted" style={{ marginTop: '0.8rem' }}>
        The agent uses AI only to decide actions — page-to-markdown conversion,
        form batches and selector retries all run locally. Every step is logged
        and a replayable recipe is recorded automatically.
      </p>
    </div>
  )
}

function normalizeUrl(value) {
  return /^https?:\/\//i.test(value) ? value : `https://${value}`
}
