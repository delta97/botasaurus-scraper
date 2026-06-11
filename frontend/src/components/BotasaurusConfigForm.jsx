const CHECKBOXES = [
  ['headless', 'Headless mode (no visible browser window)'],
  ['wait_for_complete_page_load', 'Wait for full page load (JS-heavy sites)'],
  ['block_images', 'Block images (faster)'],
  ['block_images_and_css', 'Block images and CSS (fastest)'],
  ['bypass_cloudflare', 'Attempt Cloudflare bypass on navigation'],
  ['screenshots', 'Save a screenshot after every step'],
  ['enable_xvfb_virtual_display', 'Xvfb virtual display (headful-in-container)'],
  ['human_mode', 'Humanized cursor movement (anti-detection)'],
  ['google_referer', 'Navigate via a Google referer (anti-detection)'],
]

const STEALTH_PRESET = {
  human_mode: true, google_referer: true, block_images: false,
  block_images_and_css: false, wait_for_complete_page_load: true,
}

export default function BotasaurusConfigForm({ value, onChange }) {
  const set = (key, val) => onChange({ ...value, [key]: val })
  const text = (key, label, placeholder) => (
    <label className="field">
      <span>{label}</span>
      <input
        type="text"
        value={value[key] ?? ''}
        placeholder={placeholder}
        onChange={(e) => set(key, e.target.value || null)}
      />
    </label>
  )

  return (
    <div>
      <div className="row" style={{ marginBottom: '0.6rem' }}>
        <button type="button" className="secondary small"
                onClick={() => onChange({ ...value, ...STEALTH_PRESET })}>
          Apply max-stealth preset
        </button>
      </div>
      <div className="checkbox-grid">
        {CHECKBOXES.map(([key, label]) => (
          <label key={key} className="checkbox-row">
            <input
              type="checkbox"
              checked={!!value[key]}
              onChange={(e) => set(key, e.target.checked)}
            />
            {label}
          </label>
        ))}
      </div>
      <div className="field-grid" style={{ marginTop: '0.8rem' }}>
        {text('proxy', 'Proxy', 'http://user:pass@host:port')}
        {text('user_agent', 'User agent', 'leave empty for default')}
        {text('window_size', 'Window size', '1920,1080')}
        {text('profile', 'Chrome profile name', 'persists cookies across runs')}
        <label className="field">
          <span>Max retries on crash</span>
          <input
            type="number" min="0" max="5"
            value={value.max_retry ?? 0}
            onChange={(e) => set('max_retry', parseInt(e.target.value || '0', 10))}
          />
        </label>
        <label className="field">
          <span>Result format</span>
          <select
            value={value.output_format ?? 'json'}
            onChange={(e) => set('output_format', e.target.value)}
          >
            <option value="json">JSON (structured extracts)</option>
            <option value="markdown">Markdown (page as markdown)</option>
          </select>
        </label>
      </div>
    </div>
  )
}
