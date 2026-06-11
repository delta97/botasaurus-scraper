import { useEffect, useRef, useState } from 'react'

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch { /* keep statusText */ }
    throw new Error(detail)
  }
  return res.json()
}

// Poll `fetcher` every `intervalMs` while `active` is true; always fetches once.
export function usePolling(fetcher, intervalMs, active, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  useEffect(() => {
    let cancelled = false
    let timer
    const tick = async () => {
      try {
        const result = await fetcherRef.current()
        if (!cancelled) { setData(result); setError(null) }
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
      if (!cancelled && active) timer = setTimeout(tick, intervalMs)
    }
    tick()
    return () => { cancelled = true; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, intervalMs, ...deps])

  return { data, error }
}
