import { useNavigate } from 'react-router-dom'
import { api, usePolling } from '../api'
import StatusBadge from '../components/StatusBadge'

export default function RunsPage() {
  const navigate = useNavigate()
  const { data, error } = usePolling(() => api('/api/runs'), 3000, true)

  if (error) return <div className="error-banner">{error}</div>
  const runs = data?.runs ?? []

  return (
    <div>
      <h2>Runs</h2>
      {runs.length === 0 ? (
        <p className="muted">No runs yet — start one from “New Task”.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>#</th><th>Status</th><th>Kind</th><th>Goal</th>
              <th>Tokens</th><th>Started</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => navigate(`/runs/${r.id}`)}>
                <td>{r.id}</td>
                <td><StatusBadge status={r.status} /></td>
                <td>{r.kind}</td>
                <td>{truncate(r.goal, 70)}<div className="muted">{truncate(r.start_url, 60)}</div></td>
                <td className="token-stat">
                  {r.total_prompt_tokens || r.total_completion_tokens
                    ? `${r.total_prompt_tokens} / ${r.total_completion_tokens}` : '—'}
                </td>
                <td className="muted">{r.started_at ?? r.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function truncate(text, n) {
  return text && text.length > n ? text.slice(0, n) + '…' : text
}
