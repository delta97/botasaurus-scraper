import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export default function SuitesPage() {
  const navigate = useNavigate()
  const [suites, setSuites] = useState(null)
  const [name, setName] = useState('')
  const [error, setError] = useState(null)

  const load = () => api('/api/suites').then((d) => setSuites(d.suites)).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const create = async () => {
    setError(null)
    try {
      const { suite_id } = await api('/api/suites', { method: 'POST', body: { name } })
      navigate(`/suites/${suite_id}`)
    } catch (e) { setError(e.message) }
  }

  const remove = async (e, id) => {
    e.stopPropagation()
    if (!window.confirm('Delete this suite? (recipes are kept)')) return
    try { await api(`/api/suites/${id}`, { method: 'DELETE' }); load() }
    catch (err) { setError(err.message) }
  }

  if (error && !suites) return <div className="error-banner">{error}</div>
  if (!suites) return <p className="muted">Loading…</p>

  return (
    <div>
      <h2>Test Suites</h2>
      <p className="muted">
        Group recipes into a suite, run them sequentially, and export the result
        as JUnit XML for CI.
      </p>
      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <div className="row">
          <input type="text" value={name} placeholder="new suite name"
                 style={{ flex: 1 }} onChange={(e) => setName(e.target.value)} />
          <button onClick={create} disabled={!name.trim()}>Create suite</button>
        </div>
      </div>

      {suites.length === 0 ? (
        <p className="muted">No suites yet.</p>
      ) : (
        <table>
          <thead><tr><th>#</th><th>Name</th><th>Recipes</th><th>Created</th><th /></tr></thead>
          <tbody>
            {suites.map((s) => (
              <tr key={s.id} className="clickable" onClick={() => navigate(`/suites/${s.id}`)}>
                <td>{s.id}</td>
                <td><strong>{s.name}</strong><div className="muted">{s.description}</div></td>
                <td>{s.recipe_count}</td>
                <td className="muted">{s.created_at}</td>
                <td><button className="danger small" onClick={(e) => remove(e, s.id)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
