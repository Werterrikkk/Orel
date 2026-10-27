export type Box = [number, number, number, number]
export interface Detection {
  kind: 'person' | 'helmet' | 'vest'
  box: Box
  confidence: number
  track_id?: number
}
export interface Zone {
  name: string
  points?: [number, number][] | null
  left: number
  top: number
  right: number
  bottom: number
  require_helmet: boolean
  require_vest: boolean
}
export interface Permit {
  number: string
  starts_at: string
  ends_at: string
  closed: boolean
}
export interface Configuration {
  video_id: string
  zone: Zone | null
  permit: Permit | null
}
export interface Video {
  id: string
  name: string
  width: number
  height: number
  fps: number
  duration: number
  bytes: number
  status: 'uploaded' | 'processing' | 'ready' | 'failed'
  progress: number
  error: string | null
  media_url: string
  preview_url: string
  provenance: string | null
  analysis_seconds?: number
  model?: { name: string; ppe: boolean }
}
export interface Model {
  available: boolean
  name: string
  ppe: boolean
  metrics?: Record<string, number>
  report?: string
  qualification?: string
}
export interface Bootstrap {
  server_time: string
  videos: Video[]
  models: Record<'person' | 'ppe', Model>
  demo_available: boolean
}
export interface Analysis {
  frames: { time: number; objects: Detection[]; inference_ms: number }[]
  sample_fps: number
  seconds: number
  model: Model
}
export interface SafetyEvent {
  source_type?: 'recording' | 'camera'
  id: string
  video_id: string
  video_name: string
  created_at: string
  position: number
  zone: string
  permit_number: string | null
  code: string
  reason: string
  people_count: number
  reviewed: boolean
  snapshot_url: string
  severity?: 'warning' | 'critical'
  track_id?: number
  duration_seconds?: number
  escalated_at?: string
}

export interface CameraSettings {
  require_helmet: boolean
  require_vest: boolean
  danger_zone: Omit<Zone, 'require_helmet' | 'require_vest'> | null
}
export interface CameraSession {
  id: string
  model: Model & { weights_sha256: string }
  settings: CameraSettings
}
export interface CameraObservation extends Omit<Observation, 'status'> {
  status: Observation['status'] | 'stale'
  camera_health?: 'ok' | 'obscured'
  camera_health_seconds?: number
  detections: Detection[]
  inference_ms: number
  sequence: number
  model: Model & { weights_sha256: string }
  alerts: CameraAlert[]
  pending_signals: number
}

export interface TelegramStatus {
  configured: boolean
  enabled: boolean
  bot_username: string
  chat_id: string
  pending: number
  cooldown_seconds: number
  last_test_at: string | null
  queue_error: string | null
  deliveries: {
    id: string
    status: 'pending' | 'sending' | 'sent' | 'failed' | 'uncertain' | 'expired' | 'cancelled'
    error: string | null
    severity: string
    created_at: string
    sent_at: string | null
    zone: string
  }[]
}
export interface CameraAlert {
  id: string
  track_id: number
  code: 'ppe_required' | 'danger_zone'
  message: string
  zone: string
  missing: ('helmet' | 'vest')[]
  severity: 'warning' | 'critical'
  duration_seconds: number
  escalates_after: number
}
export interface CameraSource {
  id: string
  name: string
  adapter: string
  available: boolean
  inference_location: string
  detail: string
}
export type PPEState = 'detected' | 'not_detected' | 'uncertain' | 'unavailable'
export interface Observation {
  status: 'no_zone' | 'no_people' | 'active' | 'restricted' | 'review' | 'uncertain'
  people: { box: Box; helmet: PPEState; vest: PPEState }[]
  people_in_zone: number
  people_total: number
  reasons: string[]
  uncertain: boolean
  new_events: SafetyEvent[]
  server_time: string
}
