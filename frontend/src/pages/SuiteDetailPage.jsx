import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, usePolling } from '../api'
import StatusBadge from '../components/StatusBadge'

export default function SuiteDetailPage() {
  const { id } = useParams()
  const [allRecipes, setAllRecipes] = useState([])
  const [addId, setAddId] = useState('')
  const [error, setError] = useState(null)
  const [openRun, setOpenRun] = useState(null)

  const { data: suite } = usePolling(() => api(`/api/suites/${id}`), 2500, true, [id])
  const { data: runDetail } = usePolling(
    () => openRun ? api(`/api/suites/${id}/runs/${openRun}`) : Promise.resolve(null),
    2000, !!openRun, [openRun])

  useEffect(() => {
    api('/api/recipes').then((d) => setAllRecipes(d.recipes)).catch(() => {})
  }, [])

  const act = async (fn) => {
    setError(null)
    try { await fn() } catch (e) { setError(e.message) }
  }

  const addRecipe = () => act(async () => {
    await api(`/api/suites/${id}/recipes`, { method: 'POST', body: { recipe_id: parseInt(addId, 10) } })
    setAddId('')
  })
  const removeRecipe = (srId) => act(() => api(`/api/suites/${id}/recipes/${srId}`, { method: 'DELETE' }))
  const runSuite = () => act(async () => {
    const { suite_run_id } = await api(`/api/suites/${id}/run`, { method: 'POST' })
    setOpenRun(suite_run_id)
  })
  const cancelRun = (runId) => act(() => api(`/api/suites/${id}/runs/${runId}/cancel`, { method: 'POST' }))

  if (!suite) return <p className="muted">Loading…</p>
  const inSuite = new Set(suite.recipes.map((r) => r.recipe_id))
  const addable = allRecipes.filter((r) => !inSuite.has(r.id))

  return (
    <div>
      <div className="row">
        <h2>{suite.name}</h2>
        <span className="spacer" />
        <button onClick={runSuite} disabled={suite.recipes.length === 0}>▶ Run suite</button>
      </div>
      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <h3>Recipes ({suite.recipes.length})</h3>
        {suite.recipes.length > 0 && (
          <table>
            <thead><tr><th>Order</th><th>Recipe</th><th>Variable overrides</th><th /></tr></thead>
            <tbody>
              {suite.recipes.map((r, i) => (
                <tr key={r.suite_recipe_id}>
                  <td>{i + 1}</td>
                  <td><Link to={`/recipes/${r.recipe_id}`}>{r.name}</Link></td>
                  <td className="muted">{Object.keys(r.variables).length ? JSON.stringify(r.variables) : '—'}</td>
                  <td><button className="danger small" onClick={() => removeRecipe(r.suite_recipe_id)}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row" style={{ marginTop: '0.8rem' }}>
          <select value={addId} onChange={(e) => setAddId(e.target.value)} style={{ flex: 1 }}>
            <option value="">add a recipe…</option>
            {addable.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <button className="secondary" onClick={addRecipe} disabled={!addId}>Add</button>
        </div>
      </div>

      <div className="card">
        <h3>Suite runs</h3>
        {suite.runs.length === 0 ? <p className="muted">Never run.</p> : (
          <table>
            <thead><tr><th>#</th><th>Status</th><th>Pass / fail</th><th>When</th><th /></tr></thead>
            <tbody>
              {suite.runs.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => setOpenRun(openRun === r.id ? null : r.id)}>
                  <td>{r.id}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td>{r.passed} / {r.failed} <span className="muted">of {r.total}</span></td>
                  <td className="muted">{r.started_at ?? r.created_at}</td>
                  <td className="row" onClick={(e) => e.stopPropagation()}>
                    {(r.status === 'queued' || r.status === 'running') && (
                      <button className="danger small" onClick={() => cancelRun(r.id)}>Cancel</button>
                    )}
                    <a href={`/api/suites/${id}/runs/${r.id}/junit.xml`} download>
                      <button className="secondary small">JUnit XML</button>
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {openRun && runDetail && (
          <div style={{ marginTop: '0.8rem' }}>
            <h4>Suite run #{openRun} — recipes</h4>
            <table>
              <thead><tr><th>Run</th><th>Recipe</th><th>Status</th><th>Error</th></tr></thead>
              <tbody>
                {runDetail.children.map((c) => (
                  <tr key={c.run_id}>
                    <td><Link to={`/runs/${c.run_id}`}>#{c.run_id}</Link></td>
                    <td>{c.goal?.replace('Suite run: ', '')}</td>
                    <td><StatusBadge status={c.status} /></td>
                    <td className="muted">{c.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
