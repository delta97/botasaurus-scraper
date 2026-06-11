import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge'
import VariablesForm from '../components/VariablesForm'

export default function RecipeDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [recipe, setRecipe] = useState(null)
  const [yamlText, setYamlText] = useState('')
  const [variables, setVariables] = useState({})
  const [editMode, setEditMode] = useState(false)
  const [editText, setEditText] = useState('')
  const [error, setError] = useState(null)
  const [heals, setHeals] = useState([])
  const [schedules, setSchedules] = useState([])
  const [cron, setCron] = useState('0 * * * *')

  const load = async () => {
    try {
      const data = await api(`/api/recipes/${id}`)
      setRecipe(data)
      setEditText(JSON.stringify(data.definition, null, 2))
      const res = await fetch(`/api/recipes/${id}/export?format=yaml`)
      setYamlText(await res.text())
      const h = await api(`/api/recipes/${id}/heals`)
      setHeals(h.heals)
      const sch = await api('/api/schedules')
      setSchedules(sch.schedules.filter((s) => s.recipe_id === parseInt(id, 10)))
    } catch (e) { setError(e.message) }
  }
  useEffect(() => { load() }, [id])

  const addSchedule = async () => {
    setError(null)
    try {
      await api('/api/schedules', { method: 'POST',
        body: { recipe_id: parseInt(id, 10), cron, variables } })
      load()
    } catch (e) { setError(e.message) }
  }
  const toggleSchedule = (s) => api(`/api/schedules/${s.id}`, { method: 'PUT',
    body: { enabled: !s.enabled } }).then(load).catch((e) => setError(e.message))
  const deleteSchedule = (sid) => api(`/api/schedules/${sid}`, { method: 'DELETE' })
    .then(load).catch((e) => setError(e.message))

  const uploadCsv = async (file) => {
    setError(null)
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await fetch(`/api/recipes/${id}/batch/csv`, { method: 'POST', body: form })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || res.statusText)
      alert(`Batch started: ${data.rows} rows (batch run #${data.batch_run_id}). See Runs for per-row results.`)
    } catch (e) { setError(e.message) }
  }

  const setHeal = async (patch) => {
    setError(null)
    try {
      const updated = await api(`/api/recipes/${id}`, { method: 'PUT', body: patch })
      setRecipe(updated)
    } catch (e) { setError(e.message) }
  }

  const resolveHeal = async (healId, decision) => {
    try {
      await api(`/api/recipes/${id}/heals/${healId}/${decision}`, { method: 'POST' })
      load()
    } catch (e) { setError(e.message) }
  }

  const replay = async () => {
    setError(null)
    try {
      const { run_id } = await api(`/api/recipes/${id}/replay`, {
        method: 'POST', body: { variables },
      })
      navigate(`/runs/${run_id}`)
    } catch (e) { setError(e.message) }
  }

  const saveEdit = async () => {
    setError(null)
    try {
      const definition = JSON.parse(editText)
      await api(`/api/recipes/${id}`, { method: 'PUT', body: { definition } })
      setEditMode(false)
      load()
    } catch (e) { setError(e.message) }
  }

  if (error && !recipe) return <div className="error-banner">{error}</div>
  if (!recipe) return <p className="muted">Loading…</p>

  return (
    <div>
      <div className="row">
        <h2>{recipe.name}</h2>
        <span className="spacer" />
        <a href={`/api/recipes/${id}/export?format=yaml`} download><button className="secondary small">Export YAML</button></a>
        <a href={`/api/recipes/${id}/export?format=json`} download><button className="secondary small">Export JSON</button></a>
      </div>
      <p className="muted">
        {recipe.description}
        {recipe.source_run_id && <> — recorded from <Link to={`/runs/${recipe.source_run_id}`}>run #{recipe.source_run_id}</Link></>}
      </p>
      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <h3>Replay {recipe.self_heal ? '(self-healing on)' : '(no AI involved)'}</h3>
        <VariablesForm variables={recipe.variables} values={variables} onChange={setVariables} />
        <button onClick={replay}>▶ Replay now</button>
      </div>

      <div className="card">
        <h3>Dataset (run once per CSV row)</h3>
        <p className="muted">
          Upload a CSV whose column headers match this recipe's variables
          ({recipe.variables.map((v) => `{{${v.name}}}`).join(', ') || 'none defined'}).
          Each row runs as its own replay.
        </p>
        <input type="file" accept=".csv" onChange={(e) => e.target.files[0] && uploadCsv(e.target.files[0])} />
      </div>

      <div className="card">
        <h3>Schedules</h3>
        <p className="muted">
          Cron schedules fire while the studio is running. For external cron use
          the CLI: <code>python -m backend.runner --recipe-id {recipe.id}</code>
        </p>
        {schedules.length > 0 && (
          <table>
            <thead><tr><th>Cron</th><th>Variables</th><th>Enabled</th><th>Last run</th><th /></tr></thead>
            <tbody>
              {schedules.map((s) => (
                <tr key={s.id}>
                  <td><code>{s.cron}</code></td>
                  <td className="muted">{Object.keys(s.variables).length ? JSON.stringify(s.variables) : '—'}</td>
                  <td><input type="checkbox" checked={s.enabled} onChange={() => toggleSchedule(s)} /></td>
                  <td className="muted">{s.last_run_id
                    ? <Link to={`/runs/${s.last_run_id}`}>{s.last_run_at}</Link> : 'never'}</td>
                  <td><button className="danger small" onClick={() => deleteSchedule(s.id)}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row" style={{ marginTop: '0.6rem' }}>
          <input type="text" value={cron} onChange={(e) => setCron(e.target.value)}
                 placeholder="0 * * * *" style={{ width: '160px' }} />
          <button className="secondary" onClick={addSchedule}>Add schedule</button>
          <span className="muted">uses the variable values entered above</span>
        </div>
      </div>

      <div className="card">
        <h3>Self-healing</h3>
        <label className="checkbox-row">
          <input type="checkbox" checked={recipe.self_heal}
                 onChange={(e) => setHeal({ self_heal: e.target.checked })} />
          When a selector breaks during replay, relocate the element with AI (needs an OpenRouter key)
        </label>
        {recipe.self_heal && (
          <label className="field" style={{ marginTop: '0.6rem' }}>
            <span>On a successful heal</span>
            <select value={recipe.heal_mode} onChange={(e) => setHeal({ heal_mode: e.target.value })}>
              <option value="propose">Propose — keep the recipe as-is, flag for my review</option>
              <option value="auto">Auto-apply — patch the recipe now, still flag for review</option>
            </select>
          </label>
        )}
        {heals.length > 0 && (
          <div style={{ marginTop: '0.8rem' }}>
            <h4 style={{ marginBottom: '0.4rem' }}>Healed steps</h4>
            <table>
              <thead><tr><th>Step</th><th>Was</th><th>Now</th><th>Element</th><th>Status</th><th /></tr></thead>
              <tbody>
                {heals.map((h) => (
                  <tr key={h.id}>
                    <td>#{h.step_index}{h.run_id && <> · <Link to={`/runs/${h.run_id}`}>run {h.run_id}</Link></>}</td>
                    <td className="muted"><code>{h.original_selector}</code></td>
                    <td><code>{h.healed_selector}</code></td>
                    <td className="muted">{h.element_label}</td>
                    <td><StatusBadge status={h.status} /></td>
                    <td>
                      {(h.status === 'proposed' || h.status === 'applied') && (
                        <span className="row">
                          <button className="small" onClick={() => resolveHeal(h.id, 'accept')}>Accept</button>
                          <button className="danger small" onClick={() => resolveHeal(h.id, 'reject')}>Reject</button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="row">
          <h3>Definition</h3>
          <span className="spacer" />
          <button className="secondary small" onClick={() => setEditMode(!editMode)}>
            {editMode ? 'Cancel' : 'Edit JSON'}
          </button>
          {editMode && <button className="small" onClick={saveEdit}>Save</button>}
        </div>
        {editMode ? (
          <textarea style={{ minHeight: '350px', fontFamily: 'monospace' }}
                    value={editText} onChange={(e) => setEditText(e.target.value)} />
        ) : (
          <pre className="result-block">{yamlText}</pre>
        )}
      </div>

      {recipe.replays?.length > 0 && (
        <div className="card">
          <h3>Past replays</h3>
          <table>
            <thead><tr><th>Run</th><th>Status</th><th>Variables</th><th>When</th></tr></thead>
            <tbody>
              {recipe.replays.map((r) => (
                <tr key={r.run_id} className="clickable" onClick={() => navigate(`/runs/${r.run_id}`)}>
                  <td>#{r.run_id}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td className="muted">{JSON.stringify(r.variables_used)}</td>
                  <td className="muted">{r.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
