import { useEffect, useRef, useState } from 'react'
import { rpc } from './api.js'
import { CAMELOT_CODES } from './camelot.js'
import { Bpm, CultureTag, ErrorBox, KeyChip, Meter, songHref } from './ui.jsx'

const PAGE = 50
const EMPTY = { q: '', culture: '', genre: '', bpmMin: '', bpmMax: '', camelot: '', energyMin: '', energyMax: '' }

function loadFilters() {
  try {
    return { ...EMPTY, ...JSON.parse(sessionStorage.getItem('filtreler') || '{}') }
  } catch {
    return EMPTY
  }
}

export default function Library() {
  const [f, setF] = useState(loadFilters)
  const [rows, setRows] = useState([])
  const [more, setMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [genres, setGenres] = useState([])
  const reqId = useRef(0)

  useEffect(() => {
    rpc('genre_list').then(setGenres).catch(() => setGenres([]))
  }, [])

  const params = (offset) => ({
    p_q: f.q.trim(),
    p_culture: f.culture,
    p_genre: f.genre,
    p_bpm_min: f.bpmMin,
    p_bpm_max: f.bpmMax,
    p_camelot: f.camelot,
    p_energy_min: f.energyMin === '' ? '' : Number(f.energyMin) / 100,
    p_energy_max: f.energyMax === '' ? '' : Number(f.energyMax) / 100,
    p_limit: PAGE,
    p_offset: offset,
  })

  function load(offset = 0) {
    const id = ++reqId.current
    setLoading(true)
    setError(null)
    rpc('search_songs', params(offset))
      .then((data) => {
        if (id !== reqId.current) return // eski isteğin cevabı, yok say
        setRows((prev) => (offset ? [...prev, ...data] : data))
        setMore(data.length === PAGE)
      })
      .catch((e) => id === reqId.current && setError(e))
      .finally(() => id === reqId.current && setLoading(false))
  }

  // Yazarken her tuşta değil, 300 ms durunca ara
  useEffect(() => {
    try { sessionStorage.setItem('filtreler', JSON.stringify(f)) } catch { /* gizli sekme */ }
    const t = setTimeout(() => load(0), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f])

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const active = Object.entries(f).some(([k, v]) => k !== 'q' && v !== '')

  return (
    <div className="library">
      <div className="search-row">
        <label className="sr-only" htmlFor="q">Şarkı veya sanatçı ara</label>
        <input
          id="q" className="search" type="search" autoComplete="off" value={f.q} onChange={set('q')}
          placeholder="Şarkı ya da sanatçı ara — yazım hatası sorun değil"
        />
      </div>

      <div className="filters" role="group" aria-label="Filtreler">
        <div className="seg" role="radiogroup" aria-label="Kültür">
          {[['', 'Hepsi'], ['tr', 'Türkçe'], ['global', 'Global']].map(([v, l]) => (
            <button key={v} role="radio" aria-checked={f.culture === v}
              className={f.culture === v ? 'seg-on' : ''} onClick={() => setF({ ...f, culture: v })}>{l}</button>
          ))}
        </div>
        <label className="field">
          <span>Tür</span>
          <select value={f.genre} onChange={set('genre')}>
            <option value="">Tüm türler</option>
            {genres.map((g) => <option key={g.genre} value={g.genre}>{g.genre} ({g.songs})</option>)}
          </select>
        </label>
        <label className="field field-pair">
          <span>BPM</span>
          <input type="number" inputMode="numeric" min="30" max="300" placeholder="en az" value={f.bpmMin} onChange={set('bpmMin')} />
          <input type="number" inputMode="numeric" min="30" max="300" placeholder="en çok" value={f.bpmMax} onChange={set('bpmMax')} />
        </label>
        <label className="field">
          <span>Ton</span>
          <select value={f.camelot} onChange={set('camelot')}>
            <option value="">Tüm tonlar</option>
            {CAMELOT_CODES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="field field-pair">
          <span>Enerji</span>
          <input type="number" inputMode="numeric" min="0" max="100" placeholder="0" value={f.energyMin} onChange={set('energyMin')} />
          <input type="number" inputMode="numeric" min="0" max="100" placeholder="100" value={f.energyMax} onChange={set('energyMax')} />
        </label>
        {active && <button className="btn btn-quiet" onClick={() => setF({ ...EMPTY, q: f.q })}>Filtreleri temizle</button>}
      </div>

      <ErrorBox error={error} onRetry={() => load(0)} />

      <table className="tracks">
        <thead>
          <tr>
            <th>Şarkı</th>
            <th className="col-genre">Tür</th>
            <th className="col-num">BPM</th>
            <th>Ton</th>
            <th className="col-meter">Enerji</th>
            <th className="col-meter col-dance">Dans</th>
            <th className="col-culture">Kültür</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.deezer_id} onClick={() => { location.hash = songHref(s.deezer_id) }}>
              <td className="col-title">
                <a href={songHref(s.deezer_id)} onClick={(e) => e.stopPropagation()}>
                  <span className="t">{s.track_name}</span>
                  <span className="a">{s.artist_name}</span>
                </a>
              </td>
              <td className="col-genre muted">{s.genre || '—'}</td>
              <td className="col-num"><Bpm value={s.bpm} /></td>
              <td><KeyChip code={s.camelot} /></td>
              <td className="col-meter"><Meter value={s.energy} label="Enerji" /></td>
              <td className="col-meter col-dance"><Meter value={s.danceability} label="Dans" /></td>
              <td className="col-culture"><CultureTag value={s.cultural_context} /></td>
            </tr>
          ))}
        </tbody>
      </table>

      {!loading && !error && rows.length === 0 && (
        <p className="empty">Bu aramaya uyan şarkı yok. Filtreleri gevşetin ya da başka bir ad deneyin.</p>
      )}
      <div className="list-foot">
        {loading && <span className="muted">Yükleniyor…</span>}
        {!loading && more && <button className="btn" onClick={() => load(rows.length)}>Daha fazla göster</button>}
      </div>
    </div>
  )
}
