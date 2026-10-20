import { camelotColor, compatibleKeys } from './camelot.js'

// Camelot çemberi: seçili şarkının tonu dolu, uyumlu komşuları yarı dolu,
// önerilen şarkıların tonları üzerinde küçük noktalar.
const SIZE = 300
const C = SIZE / 2
const R_OUT = 146
const R_MID = 106
const R_IN = 68

function arc(r1, r2, a0, a1) {
  const p = (r, a) => [C + r * Math.sin(a), C - r * Math.cos(a)]
  const [x1, y1] = p(r2, a0)
  const [x2, y2] = p(r2, a1)
  const [x3, y3] = p(r1, a1)
  const [x4, y4] = p(r1, a0)
  return `M${x1},${y1} A${r2},${r2} 0 0 1 ${x2},${y2} L${x3},${y3} A${r1},${r1} 0 0 0 ${x4},${y4} Z`
}

export default function CamelotWheel({ current, others = [] }) {
  const near = new Set(compatibleKeys(current))
  const counts = others.reduce((m, k) => (k ? { ...m, [k]: (m[k] || 0) + 1 } : m), {})
  const step = (2 * Math.PI) / 12

  const cells = []
  for (let n = 1; n <= 12; n++) {
    const a0 = (n - 1) * step - step / 2 + 0.012
    const a1 = (n - 1) * step + step / 2 - 0.012
    for (const ring of ['B', 'A']) {
      const code = `${n}${ring}`
      const [r1, r2] = ring === 'B' ? [R_MID + 2, R_OUT] : [R_IN, R_MID - 2]
      const isCur = code === current
      const isNear = near.has(code)
      const mid = (a0 + a1) / 2
      const rl = (r1 + r2) / 2
      cells.push(
        <g key={code}>
          <path
            d={arc(r1, r2, a0, a1)}
            fill={camelotColor(code, isCur ? 1 : isNear ? 0.45 : 0.12)}
            stroke={isCur ? 'var(--text)' : 'none'}
            strokeWidth={isCur ? 2.5 : 0}
          />
          <text x={C + rl * Math.sin(mid)} y={C - rl * Math.cos(mid) + 4} textAnchor="middle"
            className={isCur ? 'wheel-label wheel-label-cur' : 'wheel-label'}>{code}</text>
          {counts[code] && Array.from({ length: counts[code] }).map((_, i) => {
            const rd = r2 - 7
            const ad = mid + (i - (counts[code] - 1) / 2) * 0.07
            return <circle key={i} cx={C + rd * Math.sin(ad)} cy={C - rd * Math.cos(ad)} r="3.4" className="wheel-dot" />
          })}
        </g>,
      )
    }
  }

  return (
    <figure className="wheel">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img"
        aria-label={`Camelot çemberi: seçili ton ${current || 'bilinmiyor'}, önerilen tonlar ${others.join(', ')}`}>
        {cells}
        <text x={C} y={C - 4} textAnchor="middle" className="wheel-center">{current || '?'}</text>
        <text x={C} y={C + 16} textAnchor="middle" className="wheel-sub">Camelot</text>
      </svg>
      <figcaption>
        Dış halka majör, iç halka minör. Yarı dolu dilimler bu şarkıyla rahat geçiş yapılan tonlar; noktalar önerilen şarkıların tonları.
      </figcaption>
    </figure>
  )
}
