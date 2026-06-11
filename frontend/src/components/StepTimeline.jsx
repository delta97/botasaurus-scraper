import { useState } from 'react'
import StatusBadge from './StatusBadge'

export default function StepTimeline({ runId, steps }) {
  const [lightbox, setLightbox] = useState(null)
  if (!steps?.length) return <p className="muted">No steps yet…</p>

  return (
    <div className="timeline">
      {steps.map((s) => (
        <div key={s.step_index} className={`step ${s.status === 'error' ? 'error' : ''}`}>
          <span className="idx">#{s.step_index}</span>
          <span className="action">{s.action}</span>
          <span className="meta">
            {s.selector && <code>{s.selector}</code>}
            {s.selector && s.value && ' ← '}
            {s.value && <code>{truncate(s.value, 120)}</code>}
            {s.page_url && <div className="muted">{truncate(s.page_url, 100)}</div>}
            {s.error && <div className="err">{s.error}</div>}
          </span>
          <span>
            <StatusBadge status={s.status} />
            {s.duration_ms != null && <div className="token-stat">{s.duration_ms} ms</div>}
          </span>
          {s.has_screenshot && (
            <img
              className="thumb"
              src={`/api/runs/${runId}/screenshots/${s.step_index}`}
              alt={`step ${s.step_index}`}
              onClick={() => setLightbox(`/api/runs/${runId}/screenshots/${s.step_index}`)}
            />
          )}
        </div>
      ))}
      {lightbox && (
        <div className="lightbox" onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="screenshot" />
        </div>
      )}
    </div>
  )
}

function truncate(text, n) {
  return text && text.length > n ? text.slice(0, n) + '…' : text
}
