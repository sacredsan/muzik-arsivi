import { useEffect, useState } from 'react'
import { getSong, rpc } from './api.js'
import { keyName } from './camelot.js'
import CamelotWheel from './CamelotWheel.jsx'
import { DEFAULT_WEIGHTS, WEIGHT_LABELS } from './config.js'
import { Bpm, CultureTag, ErrorBox, KeyChip, Meter, songHref } from './ui.jsx'

const PARTS = [
  ['d_bpm', 'w_bpm', 'Tempo'],
  ['d_energy', 'w_energy', 'Enerji'],
  ['d_key', 'w_key', 'Ton'],
  ['d_vec', 'w_vec', 'Ses'],
  ['d_pop', 'w_pop', 'Popülerlik'],
  ['d_mood', 'w_mood', 'Ruh hali'],
]

const TIER = {
  1: 'Aynı tür, benzer alt türler',
  2: 'Aynı tür',
  3: 'Ortak etiket ya da ruh hali',
  4: 'Aynı kültür',
  5: 'Geniş havuz',
}

function fmtDur(s) {
  if (!s) return '—'
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// Önerinin skorunu oluşturan parçalar: her parça ağırlık × uzaklık; çubuk ne kadar kısaysa o kadar uyumlu
function Breakdown({ r, weights }) {
  const total = PARTS.reduce((t, [d, w]) => t + (weights[w] || 0) * (r[d] ?? 0), 0) || 1
  return (
    <span className="breakdown" title={PARTS.map(([d, w, l]) => `${l}: ${Math.round((r[d] ?? 0) * 100)}`).join(', ')}>
      {PARTS.filter(([, w]) => weights[w] > 0).map(([d, w, l]) => (
        <span key={d} className={`bd bd-${d}`} style={{ flexGrow: ((weights[w] || 0) * (r[d] ?? 0)) / total }} aria-label={l} />
      ))}
    </span>
  )
}

export default function SongDetail({ id }) {
  const [song, setSong] = useState(null)
  const [recs, setRecs] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [weights, setWeights] = useState(DEFAULT_WEIGHTS)
  const [sameCulture, setSameCulture] = useState(true)

  useEffect(() => {
    setLoading(true)
    setError(null)
    getSong(id).then(setSong).catch(setError).finally(() => setLoading(false))
    window.scrollTo(0, 0)
  }, [id])

  useEffect(() => {
    if (!song) return
    const t = setTimeout(() => {
      rpc('recommend', { p_deezer_id: song.deezer_id, p_limit: 5, p_same_culture: sameCulture, ...weights })
        .then(setRecs)
        .catch(setError)
    }, 250)
    return () => clearTimeout(t)
  }, [song, weights, sameCulture])

  if (loading) return <p className="muted pad">Yükleniyor…</p>
  if (error && !song) return <ErrorBox error={error} />
  if (!song) return <p className="empty">Bu şarkı arşivde yok. <a href="#/">Arşive dön</a></p>

  const changed = JSON.stringify(weights) !== JSON.stringify(DEFAULT_WEIGHTS) || !sameCulture
  const tags = Object.entries(song.mood_tags || {}).sort((a, b) => b[1] - a[1])

  return (
    <article className="detail">
      <a className="back" href="#/">Arşive dön</a>

      <header className="detail-head">
        <div className="detail-title">
          <h1>{song.track_name}</h1>
          <p className="detail-artist">{song.artist_name}{song.album_name ? <span className="muted"> · {song.album_name}</span> : null}</p>
          <div className="detail-meta">
            <CultureTag value={song.cultural_context} />
            {song.genre && <span className="pill">{song.genre}</span>}
            <a className="pill pill-link" href={`https://www.deezer.com/track/${song.deezer_id}`} target="_blank" rel="noreferrer">Deezer'da dinle</a>
          </div>
        </div>
        <dl className="facts">
          <div><dt>BPM</dt><dd className="fact-big"><Bpm value={song.bpm} /></dd>
            {song.bpm_raw && Math.round(song.bpm_raw) !== Math.round(song.bpm) && <dd className="muted small">ham {Math.round(song.bpm_raw)}</dd>}</div>
          <div><dt>Ton</dt><dd><KeyChip code={song.camelot} big /></dd><dd className="muted small">{keyName(song)}</dd></div>
          <div><dt>Enerji</dt><dd><Meter value={song.energy} /></dd></div>
          <div><dt>Dans edilebilirlik</dt><dd><Meter value={song.danceability} /></dd></div>
          <div><dt>Mutluluk</dt><dd><Meter value={song.mood_valence} /></dd></div>
          <div><dt>Hareket</dt><dd><Meter value={song.mood_arousal} /></dd></div>
          <div><dt>Süre</dt><dd className="num">{fmtDur(song.duration_sec)}</dd></div>
        </dl>
      </header>

      <section className="match">
        <CamelotWheel current={song.camelot} others={recs.map((r) => r.camelot)} />

        <div className="recs">
          <h2>Bu şarkıdan sonra çalabilecekleriniz</h2>
          <ErrorBox error={song && error} />
          <ol className="rec-list">
            {recs.map((r) => (
              <li key={r.deezer_id}>
                <a href={songHref(r.deezer_id)} className="rec">
                  <span className="rec-main">
                    <span className="t">{r.track_name}</span>
                    <span className="a">{r.artist_name}</span>
                  </span>
                  <span className="rec-facts">
                    <Bpm value={r.bpm} />
                    <KeyChip code={r.camelot} />
                    <Meter value={r.energy} label="Enerji" />
                  </span>
                  <span className="rec-why">
                    <span className="muted small">{TIER[r.tier]} · uyumsuzluk {Math.round(r.score * 100)}</span>
                    <Breakdown r={r} weights={weights} />
                  </span>
                </a>
              </li>
            ))}
          </ol>
          {recs.length === 0 && !error && <p className="muted">Öneriler hesaplanıyor…</p>}

          <details className="weights" open={changed}>
            <summary>Öneri ağırlıklarını dene</summary>
            <p className="muted small">
              Her kaydırıcı, o özelliğin öneride ne kadar önemli olduğunu belirler. Değişiklikler sadece bu ekranda geçerli.
            </p>
            {Object.keys(DEFAULT_WEIGHTS).map((k) => (
              <label key={k} className="slider">
                <span className={`swatch bd-${PARTS.find((p) => p[1] === k)[0]}`} />
                <span className="slider-label">{WEIGHT_LABELS[k]}</span>
                <input type="range" min="0" max="0.6" step="0.05" value={weights[k]}
                  onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) })} />
                <span className="num slider-val">{weights[k].toFixed(2)}</span>
              </label>
            ))}
            <label className="check">
              <input type="checkbox" checked={sameCulture} onChange={(e) => setSameCulture(e.target.checked)} />
              Sadece aynı kültürden öner ({song.cultural_context === 'tr' ? 'Türkçe' : 'global'})
            </label>
            {changed && (
              <button className="btn btn-quiet" onClick={() => { setWeights(DEFAULT_WEIGHTS); setSameCulture(true) }}>
                Varsayılana dön
              </button>
            )}
          </details>
        </div>
      </section>

      {(song.sub_genres?.length > 0 || tags.length > 0) && (
        <section className="tags">
          {song.sub_genres?.length > 0 && (
            <div><h3>Alt türler</h3><p>{song.sub_genres.map((g) => <span key={g} className="pill">{g}</span>)}</p></div>
          )}
          {tags.length > 0 && (
            <div><h3>Ruh hali etiketleri</h3><p>{tags.map(([t]) => <span key={t} className="pill">{t}</span>)}</p></div>
          )}
        </section>
      )}

      <p className="source-note muted small">
        Analiz: {song.analyzer || '—'} · Etiketler: {song.tag_source || '—'}
        {song.artist_country ? ` · Sanatçı ülkesi: ${song.artist_country}` : ''} · Kültür nedeni: {song.culture_reason || '—'}
      </p>
    </article>
  )
}
