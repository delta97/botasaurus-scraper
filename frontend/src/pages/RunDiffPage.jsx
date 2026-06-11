import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge'

export default function RunDiffPage() {
  const { a, b } = useParams()
  const [diff, setDiff] = useState(null)
  const [error, setError] = useState(null)
  const [onlyChanged, setOnlyChanged] = useState(false)

  useEffect(() => {
    api(`/api/runs/${a}/diff/${b}`).then(setDiff).catch((e) => setError(e.message))
  }, [a, b])

  if (error) return <div className="error-banner">{error}</div>
  if (!diff) return <p className="muted">Loading…</p>

  const rows = onlyChanged ? diff.steps.filter((s) => s.changed) : diff.steps
  const cell = (s) => s ? (
    <>
      <StatusBadge status={s.status} /> <strong>{s.action}</strong>
      {s.selector && <div className="muted"><code>{s.selector}</code></div>}
      {s.value && <div className="muted">{truncate(s.value, 60)}</div>}
      {s.error && <div className="err" style={{ color: 'var(--red)' }}>{truncate(s.error, 120)}</div>}
      <div className="token-stat">{s.duration_ms} ms</div>
    </>
  ) : <span className="muted">— missing —</span>

  return (
    <div>
      <h2>Run comparison</h2>
      <div className="row" style={{ marginBottom: '1rem' }}>
        <div className="card" style={{ flex: 1, marginBottom: 0 }}>
          <Link to={`/runs/${diff.a.id}`}>Run #{diff.a.id}</Link> <StatusBadge status={diff.a.status} />
          <div className="muted">{diff.a.started_at}</div>
        </div>
        <div className="card" style={{ flex: 1, marginBottom: 0 }}>
          <Link to={`/runs/${diff.b.id}`}>Run #{diff.b.id}</Link> <StatusBadge status={diff.b.status} />
          <div className="muted">{diff.b.started_at}</div>
        </div>
      </div>

      <label className="checkbox-row" style={{ marginBottom: '0.8rem' }}>
        <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
        Show only changed steps
      </label>

      <table>
        <thead><tr><th style={{ width: '3rem' }}>Step</th>
          <th>Run #{diff.a.id}</th><th>Run #{diff.b.id}</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.index} style={row.changed ? { background: 'rgba(224,91,91,0.07)' } : {}}>
              <td>#{row.index}</td>
              <td>{cell(row.a)}</td>
              <td>{cell(row.b)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {(diff.extracts_diff.only_a.length > 0 || diff.extracts_diff.only_b.length > 0
        || diff.extracts_diff.changed.length > 0) && (
        <div className="card" style={{ marginTop: '1rem' }}>
          <h3>Extract differences</h3>
          {diff.extracts_diff.changed.length > 0 && (
            <p>Changed values: {diff.extracts_diff.changed.join(', ')}</p>
          )}
          {diff.extracts_diff.only_a.length > 0 && (
            <p className="muted">Only in run #{diff.a.id}: {diff.extracts_diff.only_a.join(', ')}</p>
          )}
          {diff.extracts_diff.only_b.length > 0 && (
            <p className="muted">Only in run #{diff.b.id}: {diff.extracts_diff.only_b.join(', ')}</p>
          )}
        </div>
      )}
    </div>
  )
}

function truncate(text, n) {
  return text && text.length > n ? text.slice(0, n) + '…' : text
}
