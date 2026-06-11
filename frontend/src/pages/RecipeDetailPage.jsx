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

  const load = async () => {
    try {
      const data = await api(`/api/recipes/${id}`)
      setRecipe(data)
      setEditText(JSON.stringify(data.definition, null, 2))
      const res = await fetch(`/api/recipes/${id}/export?format=yaml`)
      setYamlText(await res.text())
      const h = await api(`/api/recipes/${id}/heals`)
      setHeals(h.heals)
    } catch (e) { setError(e.message) }
  }
  useEffect(() => { load() }, [id])

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
        <p className="muted" style={{ marginTop: '0.6rem' }}>
          Cron example: <code>*/30 * * * * cd /path/to/repo && python -m backend.runner --recipe-id {recipe.id}</code>
        </p>
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
