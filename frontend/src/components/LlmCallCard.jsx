export default function LlmCallCard({ call, index }) {
  const decision = extractDecision(call.response_content)
  return (
    <details className="llm-call card">
      <summary>
        LLM call #{index + 1} — {call.purpose} — {call.model}
        {' '}({call.prompt_tokens ?? '?'} in / {call.completion_tokens ?? '?'} out tokens,
        {' '}{call.latency_ms ?? '?'} ms)
        {decision && <> → <strong>{decision}</strong></>}
        {call.error && <span className="err"> — ERROR: {call.error}</span>}
      </summary>
      <h4>Request</h4>
      <pre>{JSON.stringify(call.request_messages, null, 2)}</pre>
      <h4>Response</h4>
      <pre>{JSON.stringify(call.response_content, null, 2)}</pre>
    </details>
  )
}

function extractDecision(response) {
  try {
    const tc = response?.choices?.[0]?.message?.tool_calls?.[0]?.function
      ?? response?.tool_calls?.[0]
    if (!tc) return null
    return tc.name
  } catch {
    return null
  }
}
