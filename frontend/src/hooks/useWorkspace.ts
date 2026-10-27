import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type {
  Analysis,
  Bootstrap,
  Box,
  Configuration,
  Observation,
  SafetyEvent,
  Video,
  Zone,
} from '../types'

export const defaultZone: Zone = {
  name: 'Рабочая зона № 1',
  left: 0.2,
  top: 0.2,
  right: 0.8,
  bottom: 0.92,
  require_helmet: true,
  require_vest: true,
}

export function useWorkspace() {
  const [page, setPage] = useState<'monitor' | 'events' | 'model' | 'camera'>('monitor')
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null)
  const [video, setVideo] = useState<Video | null>(null)
  const [config, setConfig] = useState<Configuration | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [observation, setObservation] = useState<Observation | null>(null)
  const [monitorUnavailable, setMonitorUnavailable] = useState(false)
  const [events, setEvents] = useState<SafetyEvent[]>([])
  const [selectedEvent, setSelectedEvent] = useState<SafetyEvent | null>(null)
  const [zoneDraft, setZoneDraft] = useState<Zone>(defaultZone)
  const [editing, setEditing] = useState(false)
  const [mode, setMode] = useState<'person' | 'ppe'>('ppe')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [clock, setClock] = useState(new Date())
  const [help, setHelp] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const sessionId = useRef(crypto.randomUUID())
  const inFlight = useRef(false)
  const initialized = useRef(false)
  const selection = useRef(0)
  const playbackEpoch = useRef(0)
  const lastObservation = useRef<number | null>(null)
  const serverOffset = useRef(0)
  const context = useRef('')
  context.current = JSON.stringify([
    page,
    video?.id,
    video?.status,
    config,
    editing,
    playbackEpoch.current,
  ])

  const reportError = useCallback(
    (value: unknown) =>
      setError(value instanceof Error ? value.message : 'Не удалось выполнить действие.'),
    [],
  )
  const refreshEvents = useCallback(async () => {
    setEvents(await api<SafetyEvent[]>('/events'))
  }, [])
  useEffect(() => {
    let active = true
    let loading = false
    const load = () => {
      if (loading) return
      loading = true
      void Promise.all([
        api<Bootstrap>('/bootstrap', { signal: AbortSignal.timeout(3000) }),
        api<SafetyEvent[]>('/events', { signal: AbortSignal.timeout(3000) }),
      ])
        .then(([data, list]) => {
          if (!active) return
          setBootstrap(data)
          setEvents(list)
          serverOffset.current = Date.parse(data.server_time) - Date.now()
          if (!initialized.current) {
            let remembered: string | null = null
            try {
              remembered = localStorage.getItem('orel:selected-video')
            } catch {
              /* Storage may be disabled. */
            }
            setVideo(data.videos.find((item) => item.id === remembered) ?? data.videos[0] ?? null)
            setMode(data.models.ppe.available ? 'ppe' : 'person')
            setError('')
            initialized.current = true
          }
        })
        .catch((value) => {
          if (active && !initialized.current) reportError(value)
        })
        .finally(() => {
          loading = false
        })
    }
    load()
    const refresh = window.setInterval(load, 5000)
    const tick = window.setInterval(
      () => setClock(new Date(Date.now() + serverOffset.current)),
      1000,
    )
    return () => {
      active = false
      clearInterval(tick)
      clearInterval(refresh)
    }
  }, [reportError])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 4500)
    return () => clearTimeout(timer)
  }, [toast])
  useEffect(() => {
    setAnalysis(null)
    setObservation(null)
    lastObservation.current = null
    setMonitorUnavailable(false)
    setConfig(null)
    setEditing(false)
    setError('')
    sessionId.current = crypto.randomUUID()
    if (!video) {
      setConfig(null)
      return
    }
    let active = true
    void api<Configuration>(`/videos/${video.id}/configuration`)
      .then((data) => {
        if (active) {
          setConfig(data)
          setZoneDraft(data.zone ?? defaultZone)
        }
      })
      .catch((value) => {
        if (active) reportError(value)
      })
    return () => {
      active = false
    }
  }, [video?.id, reportError])
  useEffect(() => {
    if (!video || video.status !== 'processing') return
    let active = true
    let polling = false
    const timer = setInterval(() => {
      if (polling) return
      polling = true
      void api<Video>(`/videos/${video.id}`, { signal: AbortSignal.timeout(3000) })
        .then((next) => {
          if (active) setVideo(next)
        })
        .catch((value) => {
          if (active) reportError(value)
        })
        .finally(() => {
          polling = false
        })
    }, 1000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [video?.id, video?.status, reportError])
  useEffect(() => {
    if (!video || video.status !== 'ready') {
      setAnalysis(null)
      return
    }
    let active = true
    void api<Analysis>(`/videos/${video.id}/detections`)
      .then((data) => {
        if (active) setAnalysis(data)
      })
      .catch((value) => {
        if (active) {
          setMonitorUnavailable(true)
          reportError(value)
        }
      })
    return () => {
      active = false
    }
  }, [video?.id, video?.status, reportError])

  const observePlayback = useCallback(async () => {
    const element = videoRef.current
    if (
      !video ||
      video.status !== 'ready' ||
      !analysis ||
      !config?.zone ||
      editing ||
      !element ||
      inFlight.current
    )
      return
    if (element.error) {
      setObservation(null)
      setMonitorUnavailable(true)
      return
    }
    inFlight.current = true
    const expectedContext = context.current
    try {
      const result = await api<Observation>('/playback', {
        method: 'POST',
        signal: AbortSignal.timeout(3000),
        body: JSON.stringify({
          session_id: sessionId.current,
          video_id: video.id,
          position: element.currentTime,
          playing: !element.paused && !element.ended,
          seeking: element.seeking,
        }),
      })
      if (context.current !== expectedContext) return
      lastObservation.current = performance.now()
      serverOffset.current = Date.parse(result.server_time) - Date.now()
      setObservation(result)
      setMonitorUnavailable(false)
      if (result.new_events.length) {
        void refreshEvents().catch(reportError)
        setToast('Новое событие сохранено в журнале')
      }
    } catch {
      if (context.current !== expectedContext) return
      setObservation(null)
      setMonitorUnavailable(true)
    } finally {
      inFlight.current = false
    }
  }, [video, analysis, config, editing, refreshEvents, reportError])
  useEffect(() => {
    const timer = setInterval(() => {
      if (lastObservation.current !== null && performance.now() - lastObservation.current > 2000) {
        setObservation(null)
        setMonitorUnavailable(true)
      }
      void observePlayback()
    }, 250)
    return () => clearInterval(timer)
  }, [observePlayback])

  async function chooseVideo(next: Video) {
    videoRef.current?.pause()
    const version = ++selection.current
    setBusy(true)
    setError('')
    try {
      const fresh = await api<Video>(`/videos/${next.id}`)
      if (selection.current !== version) return
      try {
        localStorage.setItem('orel:selected-video', fresh.id)
      } catch {
        /* Selection is optional. */
      }
      if (video?.id !== fresh.id) setConfig(null)
      setEditing(false)
      setVideo(fresh)
      setPage('monitor')
      setObservation(null)
      lastObservation.current = null
    } catch (value) {
      reportError(value)
    } finally {
      if (selection.current === version) setBusy(false)
    }
  }
  async function upload(file?: File) {
    if (!file) return
    if (file.size > 200 * 1024 * 1024) {
      setError('Размер видео должен быть не более 200 МБ.')
      return
    }
    setBusy(true)
    setError('')
    const body = new FormData()
    body.append('file', file)
    try {
      const next = await api<Video>('/videos', { method: 'POST', body })
      setBootstrap((current) =>
        current ? { ...current, videos: [next, ...current.videos] } : current,
      )
      await chooseVideo(next)
      setToast('Видео загружено. Выделите зону и запустите анализ.')
    } catch (value) {
      reportError(value)
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }
  async function openDemo() {
    setBusy(true)
    setError('')
    try {
      const next = await api<Video>('/demo', { method: 'POST' })
      setBootstrap((current) =>
        current
          ? {
              ...current,
              videos: [next, ...current.videos.filter((item) => item.id !== next.id)],
            }
          : current,
      )
      await chooseVideo(next)
    } catch (value) {
      reportError(value)
    } finally {
      setBusy(false)
    }
  }
  async function saveConfig(next: Configuration) {
    const version = selection.current
    setBusy(true)
    setError('')
    try {
      const saved = await api<Configuration>(`/videos/${next.video_id}/configuration`, {
        method: 'PUT',
        body: JSON.stringify(next),
      })
      if (selection.current !== version) return
      setConfig(saved)
      lastObservation.current = null
      setMonitorUnavailable(false)
      setZoneDraft(saved.zone ?? defaultZone)
      setObservation(null)
      setEditing(false)
      setToast('Настройки сохранены')
    } catch (value) {
      reportError(value)
    } finally {
      setBusy(false)
    }
  }
  async function startAnalysis() {
    if (!video) return
    sessionId.current = crypto.randomUUID()
    videoRef.current?.pause()
    setBusy(true)
    setError('')
    setObservation(null)
    lastObservation.current = null
    try {
      setVideo(
        await api<Video>(`/videos/${video.id}/analysis`, {
          method: 'POST',
          body: JSON.stringify({ model: mode }),
        }),
      )
    } catch (value) {
      reportError(value)
    } finally {
      setBusy(false)
    }
  }
  async function reviewEvent(event: SafetyEvent) {
    try {
      const updated = await api<SafetyEvent>(`/events/${event.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ reviewed: !event.reviewed }),
      })
      setSelectedEvent((current) => (current?.id === event.id ? updated : current))
      await refreshEvents()
    } catch (value) {
      reportError(value)
    }
  }
  function changePage(next: typeof page) {
    videoRef.current?.pause()
    lastObservation.current = null
    setObservation(null)
    setPage(next)
  }
  function resetPlayback() {
    playbackEpoch.current += 1
    context.current = ''
    sessionId.current = crypto.randomUUID()
    lastObservation.current = null
    setObservation(null)
    setMonitorUnavailable(false)
  }
  function drawZone(box: Box) {
    setZoneDraft((current) => ({
      ...current,
      left: box[0],
      top: box[1],
      right: box[2],
      bottom: box[3],
    }))
  }

  return {
    page,
    bootstrap,
    video,
    config,
    analysis,
    observation,
    monitorUnavailable,
    events,
    selectedEvent,
    zoneDraft,
    editing,
    mode,
    busy,
    error,
    toast,
    clock,
    help,
    fileInput,
    videoRef,
    setSelectedEvent,
    setZoneDraft,
    setEditing,
    setMode,
    setError,
    setHelp,
    upload,
    openDemo,
    saveConfig,
    startAnalysis,
    reviewEvent,
    changePage,
    drawZone,
    chooseVideo,
    observePlayback,
    refreshEvents,
    resetPlayback,
  }
}

export type Workspace = ReturnType<typeof useWorkspace>
