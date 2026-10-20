// Supabase bağlantısı. Bu anahtar "publishable" (herkese açık) anahtardır:
// tarayıcıda görünmesi normaldir, yalnızca OKUMA yapabilir (RLS ile korunur).
// GİZLİ anahtar (sb_secret_...) ASLA buraya yazılmaz.
export const SUPABASE_URL =
  import.meta.env?.VITE_SUPABASE_URL || 'https://icedddkahnftbqlhznpn.supabase.co'
export const SUPABASE_KEY =
  import.meta.env?.VITE_SUPABASE_KEY || 'sb_publishable_287FgjZRTNHVMPW265VmtA_F_PPSl6o'

// Öneri ağırlıkları (CLAUDE.md §6). Panelde değiştirilip denenebilir.
export const DEFAULT_WEIGHTS = { w_bpm: 0.3, w_energy: 0.2, w_key: 0.2, w_vec: 0.2, w_pop: 0.1, w_mood: 0 }

export const WEIGHT_LABELS = {
  w_bpm: 'Tempo (BPM)',
  w_energy: 'Enerji',
  w_key: 'Ton uyumu',
  w_vec: 'Ses benzerliği',
  w_pop: 'Popülerlik',
  w_mood: 'Ruh hali',
}
