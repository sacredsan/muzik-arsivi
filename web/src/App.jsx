import { useEffect, useState } from 'react'
import Library from './Library.jsx'
import SongDetail from './SongDetail.jsx'
import Stats from './Stats.jsx'

// Basit adres yönlendirmesi: #/ arşiv, #/sarki/123 şarkı, #/istatistik
function useRoute() {
  const [hash, setHash] = useState(location.hash || '#/')
  useEffect(() => {
    const on = () => setHash(location.hash || '#/')
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])
  return hash
}

export default function App() {
  const hash = useRoute()
  const song = /^#\/sarki\/(\d+)/.exec(hash)
  const page = song ? 'song' : hash.startsWith('#/istatistik') ? 'stats' : 'library'

  useEffect(() => {
    document.title = page === 'stats' ? 'İstatistik · Müzik Arşivi' : 'Müzik Arşivi'
  }, [page])

  return (
    <>
      <header className="top">
        <a className="brand" href="#/">
          <svg viewBox="0 0 24 24" aria-hidden="true" className="brand-mark">
            {Array.from({ length: 12 }).map((_, i) => (
              <circle key={i} cx={12 + 9 * Math.sin((i * Math.PI) / 6)} cy={12 - 9 * Math.cos((i * Math.PI) / 6)} r="1.9"
                fill={`hsl(${(75 + i * 30) % 360} 70% 60%)`} />
            ))}
          </svg>
          Müzik Arşivi
        </a>
        <nav>
          <a href="#/" aria-current={page !== 'stats' ? 'page' : undefined}>Arşiv</a>
          <a href="#/istatistik" aria-current={page === 'stats' ? 'page' : undefined}>İstatistik</a>
        </nav>
      </header>
      <main>
        {page === 'library' && <Library />}
        {page === 'song' && <SongDetail id={song[1]} />}
        {page === 'stats' && <Stats />}
      </main>
    </>
  )
}
