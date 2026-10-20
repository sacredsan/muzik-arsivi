import { useEffect, useState } from 'react'
import { rpc } from './api.js'
import { ErrorBox } from './ui.jsx'

const DB_LIMIT_MB = 500

function ago(iso) {
  if (!iso) return '—'
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 1) return 'şimdi'
  if (m < 60) return `${m} dk önce`
  const h = Math.round(m / 60)
  return h < 48 ? `${h} sa önce` : `${Math.round(h / 24)} gün önce`
}

function workerName(w) {
  const k = (w || '').split('-')[0]
  return { cloudrun: 'Google Cloud Run', gha: 'GitHub Actions', oracle: 'Oracle sunucusu' }[k] || w
}

export default function Stats() {
  const [s, setS] = useState(null)
  const [error, setError] = useState(null)

  const load = () => {
    setError(null)
    rpc('archive_stats').then(setS).catch(setError)
  }
  useEffect(() => {
    load()
    const t = setInterval(load, 60000) // dakikada bir tazele
    return () => clearInterval(t)
  }, [])

  if (error) return <ErrorBox error={error} onRetry={load} />
  if (!s) return <p className="muted pad">Yükleniyor…</p>

  const q = s.queue || {}
  const tr = s.by_culture?.tr || 0
  const gl = s.by_culture?.global || 0
  const maxG = Math.max(1, ...(s.top_genres || []).map((g) => g.count))
  const dbPct = (s.db_size_mb / DB_LIMIT_MB) * 100

  return (
    <div className="stats">
      <section className="stat-hero">
        <p className="stat-total"><span className="num">{s.total_songs.toLocaleString('tr-TR')}</span> şarkı analiz edildi</p>
        <div className="culture-bar" aria-label={`Türkçe ${tr}, global ${gl}`}>
          <span className="cb-tr" style={{ flexGrow: tr }}>Türkçe {tr.toLocaleString('tr-TR')}</span>
          <span className="cb-gl" style={{ flexGrow: gl }}>Global {gl.toLocaleString('tr-TR')}</span>
        </div>
      </section>

      <div className="stat-grid">
        <section>
          <h2>Kuyruk</h2>
          <dl className="kv">
            <div><dt>Sırada bekleyen</dt><dd className="num">{(q.pending || 0).toLocaleString('tr-TR')}</dd></div>
            <div><dt>Şu an işlenen</dt><dd className="num">{q.processing || 0}</dd></div>
            <div><dt>Analiz edilemeyen</dt><dd className="num">{q.failed || 0}</dd></div>
            <div><dt>Hata oranı (24 saat)</dt><dd className="num">%{((s.failure_rate_24h || 0) * 100).toFixed(1)}</dd></div>
          </dl>
          <p className="muted small">Analiz edilemeyenlerin çoğu Deezer'da 30 saniyelik örneği olmayan şarkılar.</p>
        </section>

        <section>
          <h2>Veritabanı</h2>
          <p className="num big">{Number(s.db_size_mb).toLocaleString('tr-TR')} MB <span className="muted small">/ {DB_LIMIT_MB} MB</span></p>
          <div className="meter-track wide"><span className="meter-fill" style={{ width: `${Math.max(1, dbPct)}%` }} /></div>
          <p className="muted small">Ücretsiz planın %{dbPct.toFixed(1)} kadarı kullanılıyor; %80'de Telegram uyarısı gelir.</p>
        </section>

        <section className="span-2">
          <h2>En çok şarkısı olan türler</h2>
          <ul className="bars">
            {(s.top_genres || []).map((g) => (
              <li key={g.genre}>
                <span className="bar-label">{g.genre}</span>
                <span className="bar"><span style={{ width: `${(g.count / maxG) * 100}%` }} /></span>
                <span className="num">{g.count}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="span-2">
          <h2>Ajanların son çalışmaları</h2>
          <table className="runs">
            <thead><tr><th>Ajan</th><th>Başladı</th><th className="col-num">İşlenen</th><th className="col-num">Atlanan</th><th className="col-num">Hatalı</th></tr></thead>
            <tbody>
              {(s.recent_runs || []).map((r, i) => (
                <tr key={i}>
                  <td>{workerName(r.worker)}</td>
                  <td>{ago(r.started_at)}{!r.finished_at && <span className="live"> · çalışıyor</span>}</td>
                  <td className="col-num num">{r.processed}</td>
                  <td className="col-num num">{r.skipped}</td>
                  <td className="col-num num">{r.failed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  )
}
