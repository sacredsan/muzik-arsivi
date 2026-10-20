import { camelotColor } from './camelot.js'

export function KeyChip({ code, big = false }) {
  if (!code) return <span className="muted">—</span>
  return (
    <span className={big ? 'key-chip key-chip-big' : 'key-chip'} style={{ '--key': camelotColor(code) }}>
      {code}
    </span>
  )
}

// 0..1 arası değeri ince çubuk olarak gösterir
export function Meter({ value, label }) {
  if (value === null || value === undefined) return <span className="muted">—</span>
  const pct = Math.round(value * 100)
  return (
    <span className="meter" title={`${label ? label + ': ' : ''}${pct}/100`}>
      <span className="meter-track"><span className="meter-fill" style={{ width: `${pct}%` }} /></span>
      <span className="meter-num">{pct}</span>
    </span>
  )
}

export function Bpm({ value }) {
  if (!value) return <span className="muted">—</span>
  return <span className="num">{Math.round(value)}</span>
}

export function CultureTag({ value }) {
  return <span className={`culture culture-${value}`}>{value === 'tr' ? 'Türkçe' : 'Global'}</span>
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null
  return (
    <div className="error-box" role="alert">
      <p>Veriler yüklenemedi. {error.message}</p>
      {onRetry && <button className="btn" onClick={onRetry}>Tekrar dene</button>}
    </div>
  )
}

export function songHref(id) {
  return `#/sarki/${id}`
}
