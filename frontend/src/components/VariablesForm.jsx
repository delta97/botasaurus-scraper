export default function VariablesForm({ variables, values, onChange }) {
  if (!variables?.length) return <p className="muted">This recipe has no variables.</p>
  return (
    <div className="field-grid">
      {variables.map((v) => (
        <label key={v.name} className="field">
          <span>{'{{'}{v.name}{'}}'}{v.description ? ` — ${v.description}` : ''}</span>
          <input
            type="text"
            value={values[v.name] ?? v.default ?? ''}
            onChange={(e) => onChange({ ...values, [v.name]: e.target.value })}
          />
        </label>
      ))}
    </div>
  )
}
