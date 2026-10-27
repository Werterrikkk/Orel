import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { CameraObservation, CameraSession, CameraSettings } from '../types'

const framePeriod = 200

function cameraError(value: unknown): string {
  if (value instanceof ApiError && value.status === 404)
    return 'Запущена старая версия сервера. Перезапустите приложение через scripts/start.sh.'
  if (value instanceof DOMException) {
    if (value.name === 'NotAllowedError')
      return 'Доступ к камере запрещён. Разрешите его в браузере и настройках конфиденциальности macOS.'
    if (value.name === 'NotFoundError')
      return 'Камера не найдена. Проверьте подключение и выберите устройство.'
    if (value.name === 'NotReadableError')
      return 'Камера недоступна. Закройте другие приложения, которые могут её использовать.'
    if (value.name === 'OverconstrainedError')
      return 'Выбранная камера недоступна. Выберите другую.'
    if (value.name === 'TimeoutError')
      return 'Сервер не ответил вовремя. Проверьте, что приложение запущено, и включите камеру повторно.'
  }
  if (value instanceof TypeError)
    return 'Нет связи с локальным сервером. Проверьте, что приложение запущено.'
  return value instanceof Error ? value.message : 'Не удалось включить камеру.'
}

export function useCamera(onEvents: () => void) {
  const [phase, setPhase] = useState<'off' | 'starting' | 'running' | 'error'>('off')
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [observation, setObservation] = useState<CameraObservation | null>(null)
  const [settings, setSettings] = useState<CameraSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [delayed, setDelayed] = useState(false)
  const [roundtrip, setRoundtrip] = useState<number | null>(null)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState('')
  const videoRef = useRef<HTMLVideoElement>(null)
  const session = useRef<CameraSession | null>(null)
  const media = useRef<MediaStream | null>(null)
  const request = useRef<AbortController | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const generation = useRef(0)
  const settingsVersion = useRef(0)
  const settingsPending = useRef(false)
  const lastResult = useRef<number | null>(null)
  const onEventsRef = useRef(onEvents)
  onEventsRef.current = onEvents

  const stop = useCallback((update = true, error = '') => {
    generation.current += 1
    request.current?.abort()
    if (timer.current) clearTimeout(timer.current)
    media.current?.getTracks().forEach((track) => {
      track.onended = null
      track.stop()
    })
    media.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    const previous = session.current
    session.current = null
    lastResult.current = null
    if (previous)
      void api<void>(`/camera/sessions/${previous.id}`, {
        method: 'DELETE',
        keepalive: true,
        signal: AbortSignal.timeout(3000),
      }).catch(() => {
        /* The server lease also expires when frames stop. */
      })
    if (update) {
      setStream(null)
      setObservation(null)
      setDelayed(false)
      setRoundtrip(null)
      setPhase(error ? 'error' : 'off')
      setMessage(error)
    }
  }, [])

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return
    const list = await navigator.mediaDevices.enumerateDevices()
    setDevices(list.filter((device) => device.kind === 'videoinput'))
  }, [])

  useEffect(() => {
    let active = true
    void api<CameraSettings>('/camera/configuration')
      .then((data) => {
        if (active) setSettings(data)
      })
      .catch((error) => {
        if (active) setMessage(cameraError(error))
      })
    void refreshDevices().catch(() => {})
    const leaving = () => stop(false)
    const hidden = () => {
      if (document.hidden) stop()
    }
    window.addEventListener('pagehide', leaving)
    document.addEventListener('visibilitychange', hidden)
    return () => {
      active = false
      stop(false)
      window.removeEventListener('pagehide', leaving)
      document.removeEventListener('visibilitychange', hidden)
    }
  }, [refreshDevices, stop])

  useEffect(() => {
    if (phase !== 'running') return
    const watchdog = setInterval(() => {
      if (lastResult.current !== null && performance.now() - lastResult.current > 2000) {
        setObservation(null)
        setDelayed(true)
      }
    }, 250)
    return () => clearInterval(watchdog)
  }, [phase])

  async function start() {
    if (phase === 'starting' || phase === 'running') return
    stop()
    const version = generation.current
    setPhase('starting')
    setMessage('')
    let opened: CameraSession | null = null
    try {
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error('Откройте приложение через localhost в браузере с поддержкой камеры.')
      const captured = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          ...(deviceId ? { deviceId: { exact: deviceId } } : { facingMode: 'user' }),
        },
        audio: false,
      })
      if (version !== generation.current) {
        captured.getTracks().forEach((track) => track.stop())
        return
      }
      media.current = captured
      setStream(captured)
      captured.getVideoTracks()[0].onended = () =>
        stop(true, 'Камера отключилась. Включите её повторно.')
      opened = await api<CameraSession>('/camera/sessions', {
        method: 'POST',
        signal: AbortSignal.timeout(5000),
      })
      if (version !== generation.current) {
        void api<void>(`/camera/sessions/${opened.id}`, { method: 'DELETE' }).catch(() => {})
        return
      }
      session.current = opened
      setSettings(opened.settings)
      setPhase('running')
      void refreshDevices().catch(() => {})
      const canvas = document.createElement('canvas')
      let sequence = 0
      let lastVideoTime = -1
      const started = performance.now()
      const pump = async () => {
        if (version !== generation.current || !session.current) return
        const element = videoRef.current
        const track = captured.getVideoTracks()[0]
        if (!track || track.readyState !== 'live') {
          stop(true, 'Камера отключилась. Включите её повторно.')
          return
        }
        if (
          !element ||
          element.readyState < 2 ||
          !element.videoWidth ||
          track.muted ||
          element.currentTime === lastVideoTime
        ) {
          if (performance.now() - started > 10_000 && lastResult.current === null) {
            stop(true, 'Камера не передаёт кадры. Проверьте её и повторите запуск.')
            return
          }
          timer.current = setTimeout(() => void pump(), framePeriod)
          return
        }
        lastVideoTime = element.currentTime
        const expectedSettings = settingsVersion.current
        const before = performance.now()
        const scale = Math.min(1, 640 / Math.max(element.videoWidth, element.videoHeight))
        canvas.width = Math.round(element.videoWidth * scale)
        canvas.height = Math.round(element.videoHeight * scale)
        try {
          const context = canvas.getContext('2d')
          if (!context) throw new Error('Браузер не смог подготовить кадр камеры.')
          context.drawImage(element, 0, 0, canvas.width, canvas.height)
          const jpeg = await new Promise<Blob | null>((resolve) =>
            canvas.toBlob(resolve, 'image/jpeg', 0.8),
          )
          if (version !== generation.current) return
          if (!jpeg) throw new Error('Не удалось получить кадр камеры.')
          const body = new FormData()
          body.append('file', jpeg, 'camera.jpg')
          request.current = new AbortController()
          const result = await api<CameraObservation>(
            `/camera/sessions/${opened!.id}/frames?sequence=${sequence++}`,
            {
              method: 'POST',
              body,
              signal: AbortSignal.any([request.current.signal, AbortSignal.timeout(15_000)]),
            },
          )
          if (
            version !== generation.current ||
            settingsVersion.current !== expectedSettings ||
            settingsPending.current
          )
            return
          if (result.status === 'stale' || performance.now() - before > 2000) {
            setObservation(null)
            setDelayed(true)
          } else {
            lastResult.current = performance.now()
            setObservation(result)
            setDelayed(false)
            setRoundtrip(Math.round(performance.now() - before))
          }
          if (result.new_events.length) onEventsRef.current()
        } catch (error) {
          if (version !== generation.current) return
          if (!(error instanceof ApiError && error.status === 429)) {
            stop(true, cameraError(error))
            return
          }
        } finally {
          if (version === generation.current)
            timer.current = setTimeout(
              () => void pump(),
              Math.max(0, framePeriod - (performance.now() - before)),
            )
        }
      }
      void pump()
    } catch (error) {
      if (version === generation.current) stop(true, cameraError(error))
    }
  }

  async function saveSettings(next: CameraSettings) {
    setSaving(true)
    setMessage('')
    settingsVersion.current += 1
    settingsPending.current = true
    setObservation(null)
    lastResult.current = null
    try {
      setSettings(
        await api<CameraSettings>('/camera/configuration', {
          method: 'PUT',
          body: JSON.stringify(next),
        }),
      )
      return true
    } catch (error) {
      setMessage(cameraError(error))
      return false
    } finally {
      settingsPending.current = false
      settingsVersion.current += 1
      setSaving(false)
    }
  }

  return {
    phase,
    stream,
    observation,
    settings,
    saving,
    message,
    delayed,
    roundtrip,
    devices,
    deviceId,
    setDeviceId,
    videoRef,
    start,
    stop,
    saveSettings,
  }
}
