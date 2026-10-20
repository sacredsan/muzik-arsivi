// Camelot çemberi: 1-12 saat yönünde; A = minör (iç halka), B = majör (dış halka).
// Her sayıya çember üzerinde kendi rengi verilir; DJ yazılımlarındaki renkli ton çemberine benzer.

export const CAMELOT_CODES = Array.from({ length: 12 }, (_, i) => [`${i + 1}A`, `${i + 1}B`]).flat()

export function parseCamelot(code) {
  const m = /^(\d{1,2})([AB])$/.exec(code || '')
  if (!m) return null
  return { n: Number(m[1]), ring: m[2] }
}

export function camelotColor(code, alpha = 1) {
  const p = parseCamelot(code)
  if (!p) return `hsla(220, 8%, 55%, ${alpha})`
  // 1 = sarımsı yeşil, saat yönünde renk tekerleği
  const hue = (75 + (p.n - 1) * 30) % 360
  return p.ring === 'B' ? `hsla(${hue}, 78%, 66%, ${alpha})` : `hsla(${hue}, 62%, 52%, ${alpha})`
}

// Komşu tonlar (uyumlu geçişler): aynı sayı diğer halka, ±1 aynı halka
export function compatibleKeys(code) {
  const p = parseCamelot(code)
  if (!p) return []
  const wrap = (n) => ((n - 1 + 12) % 12) + 1
  return [`${p.n}${p.ring === 'A' ? 'B' : 'A'}`, `${wrap(p.n - 1)}${p.ring}`, `${wrap(p.n + 1)}${p.ring}`]
}

export function keyName(song) {
  if (!song?.musical_key) return ''
  return `${song.musical_key} ${song.key_scale === 'minor' ? 'minör' : 'majör'}`
}
