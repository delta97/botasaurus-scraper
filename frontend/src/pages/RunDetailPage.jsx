import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, usePolling } from '../api'
import LlmCallCard from '../components/LlmCallCard'
import StatusBadge from '../components/StatusBadge'
import StepTimeline from '../components/StepTimeline'

const LIVE = ['queued', 'running']

export default function RunDetailPage() {
  const { id } = useParams()
  const [saveOpen, setSaveOpen] = useState(false)
  const [recipeName, setRecipeName] = useState('')
  const [savedRecipeId, setSavedRecipeId] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [previousRunId, setPreviousRunId] = useState(null)

  const { data: run } = usePolling(() => api(`/api/runs/${id}`), 1500, true, [id])
  const live = run ? LIVE.includes(run.status) : true
  const { data: stepsData } = usePolling(() => api(`/api/runs/${id}/steps`), 1500, live, [id])
  const { data: llmData } = usePolling(() => api(`/api/runs/${id}/llm_calls`), 2500, live, [id])

  // offer a diff against the previous run of the same recipe
  useEffect(() => {
    if (!run?.recipe_id) return
    api(`/api/recipes/${run.recipe_id}`).then((recipe) => {
      const prev = (recipe.replays || []).find((r) => r.run_id < run.id)
      setPreviousRunId(prev ? prev.run_id : null)
    }).catch(() => {})
  }, [run?.recipe_id, run?.id])

  if (!run) return <p className="muted">Loading…</p>
  const result = run.result
  const recordedSteps = result?.recorded_steps ?? []

  const cancel = async () => {
    try { await api(`/api/runs/${id}/cancel`, { method: 'POST' }) }
    catch (e) { setActionError(e.message) }
  }

  const saveRecipe = async () => {
    setActionError(null)
    try {
      const { recipe_id } = await api(`/api/runs/${id}/save_recipe`, {
        method: 'POST',
        body: { name: recipeName || `run-${id}`, variablize: true },
      })
      setSavedRecipeId(recipe_id)
      setSaveOpen(false)
    } catch (e) { setActionError(e.message) }
  }

  return (
    <div>
      <div className="row">
        <h2>Run #{run.id}</h2>
        <StatusBadge status={run.status} />
        <span className="spacer" />
        {previousRunId && (
          <Link to={`/runs/${previousRunId}/diff/${run.id}`}>
            <button className="secondary small">Compare with run #{previousRunId}</button>
          </Link>
        )}
        {LIVE.includes(run.status) && (
          <button className="danger small" onClick={cancel}>Cancel</button>
        )}
        {run.status === 'succeeded' && run.kind === 'agent' && recordedSteps.length > 0 && (
          <button className="small" onClick={() => setSaveOpen(!saveOpen)}>Save as recipe</button>
        )}
      </div>

      <p className="muted">
        {run.goal} — <code>{run.start_url}</code>
        {run.model && <> — model: {run.model}</>}
        {(run.total_prompt_tokens > 0 || run.total_completion_tokens > 0) && (
          <> — tokens: {run.total_prompt_tokens} in / {run.total_completion_tokens} out</>
        )}
      </p>

      {actionError && <div className="error-banner">{actionError}</div>}
      {run.error && <div className="error-banner">{run.error}</div>}
      {savedRecipeId && (
        <div className="success-banner">
          Recipe saved — <Link to={`/recipes/${savedRecipeId}`}>open it</Link> to replay or export.
        </div>
      )}

      {saveOpen && (
        <div className="card">
          <h3>Save as replayable recipe</h3>
          <label className="field">
            <span>Recipe name</span>
            <input type="text" value={recipeName} placeholder={`run-${id}`}
                   onChange={(e) => setRecipeName(e.target.value)} />
          </label>
          <p className="muted">
            Typed values are converted to {'{{variables}}'} so you can replay with different data.
          </p>
          <button onClick={saveRecipe}>Save recipe</button>
        </div>
      )}

      {result?.summary && <div className="card"><h3>Summary</h3><p>{result.summary}</p></div>}
      {result?.answer && <div className="card"><h3>Answer</h3><pre className="result-block">{result.answer}</pre></div>}
      {result?.extracts && Object.keys(result.extracts).length > 0 && (
        <div className="card">
          <h3>Extracted content</h3>
          {Object.entries(result.extracts).map(([key, value]) => (
            <details key={key} className="collapse" open={Object.keys(result.extracts).length === 1}>
              <summary>{key} ({String(value).length} chars)</summary>
              <pre className="result-block">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>
            </details>
          ))}
        </div>
      )}

      <div className="card">
        <h3>Step timeline</h3>
        <StepTimeline runId={id} steps={stepsData?.steps} />
      </div>

      {llmData?.llm_calls?.length > 0 && (
        <div className="card">
          <h3>LLM calls ({llmData.llm_calls.length})</h3>
          {llmData.llm_calls.map((c, i) => <LlmCallCard key={c.id} call={c} index={i} />)}
        </div>
      )}
    </div>
  )
}
