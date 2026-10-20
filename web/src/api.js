import { SUPABASE_KEY, SUPABASE_URL } from './config.js'

const headers = { apikey: SUPABASE_KEY, 'Content-Type': 'application/json' }

async function handle(res) {
  if (!res.ok) {
    let msg = `Sunucu hatası (${res.status})`
    try {
      const j = await res.json()
      if (j.message) msg += `: ${j.message}`
    } catch { /* gövde yoksa */ }
    throw new Error(msg)
  }
  return res.json()
}

export function rpc(name, params = {}) {
  // Boş filtreleri gönderme (fonksiyon varsayılanı kullanılsın)
  const body = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined))
  return fetch(`${SUPABASE_URL}/rest/v1/rpc/${name}`, { method: 'POST', headers, body: JSON.stringify(body) }).then(handle)
}

export async function getSong(deezerId) {
  const cols = [
    'deezer_id', 'track_name', 'artist_name', 'album_name', 'genre', 'sub_genres', 'mood_tags', 'cultural_context',
    'culture_reason', 'artist_country', 'bpm', 'bpm_raw', 'bpm_conf', 'musical_key', 'key_scale', 'key_conf', 'camelot',
    'energy', 'danceability', 'mood_valence', 'mood_arousal', 'duration_sec', 'deezer_rank', 'isrc', 'analyzer',
    'tag_source', 'created_at',
  ].join(',')
  const rows = await fetch(
    `${SUPABASE_URL}/rest/v1/songs?deezer_id=eq.${encodeURIComponent(deezerId)}&select=${cols}`,
    { headers },
  ).then(handle)
  return rows[0] || null
}
