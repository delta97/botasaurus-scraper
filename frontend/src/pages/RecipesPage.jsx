import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export default function RecipesPage() {
  const navigate = useNavigate()
  const [recipes, setRecipes] = useState(null)
  const [error, setError] = useState(null)

  const load = () => api('/api/recipes').then((d) => setRecipes(d.recipes)).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const remove = async (e, id) => {
    e.stopPropagation()
    if (!window.confirm('Delete this recipe?')) return
    try { await api(`/api/recipes/${id}`, { method: 'DELETE' }); load() }
    catch (err) { setError(err.message) }
  }

  if (error) return <div className="error-banner">{error}</div>
  if (!recipes) return <p className="muted">Loading…</p>

  return (
    <div>
      <h2>Recipes</h2>
      <p className="muted">
        Deterministic, AI-free automations recorded from successful runs.
        Replay them here, export as JSON/YAML, or schedule with cron via{' '}
        <code>python -m backend.runner --recipe-id N</code>.
      </p>
      {recipes.length === 0 ? (
        <p className="muted">No recipes yet — finish an agent run and click “Save as recipe”.</p>
      ) : (
        <table>
          <thead>
            <tr><th>#</th><th>Name</th><th>Description</th><th>Variables</th><th>Created</th><th /></tr>
          </thead>
          <tbody>
            {recipes.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => navigate(`/recipes/${r.id}`)}>
                <td>{r.id}</td>
                <td><strong>{r.name}</strong></td>
                <td className="muted">{r.description}</td>
                <td className="muted">{r.variables.map((v) => v.name).join(', ') || '—'}</td>
                <td className="muted">{r.created_at}</td>
                <td><button className="danger small" onClick={(e) => remove(e, r.id)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
