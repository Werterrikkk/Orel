import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Camera, Expand, Settings2, Square, X } from 'lucide-react'
import { useCamera } from '../hooks/useCamera'
import { useCameraPreview } from '../hooks/useCameraPreview'
import type { CameraSettings, SafetyEvent } from '../types'
import { DetectionBoxes } from './DetectionBoxes'

type Point = [number, number]
interface Props {
  modelAvailable: boolean
  blocked: boolean
  events: SafetyEvent[]
  onEvents: () => void
  onSelect: (event: SafetyEvent) => void
  onAll: () => void
}
const initial: CameraSettings = { require_helmet: true, require_vest: false, danger_zone: null }
export function CameraWorkspace({ modelAvailable, blocked, events, onEvents, onAll }: Props) {
  const camera = useCamera(onEvents)
  const preview = useCameraPreview(camera.videoRef, camera.stream)
  const viewport = useRef<HTMLDivElement>(null)
  const [panel, setPanel] = useState(false)
  const [editing, setEditing] = useState(false)
  const [points, setPoints] = useState<Point[]>([])
  const [draft, setDraft] = useState<CameraSettings>(initial)
  const [saved, setSaved] = useState(false)
  const [size, setSize] = useState({ width: 960, height: 540 })
  const [ratio, setRatio] = useState(16 / 9)
  const observation = camera.observation
  const connected = camera.phase === 'running' || camera.phase === 'starting'
  const obscured = observation?.camera_health === 'obscured'
  const zone = camera.settings?.danger_zone
  const gearStatus = (kind: 'helmet' | 'vest') => {
    const required =
      kind === 'helmet' ? camera.settings?.require_helmet : camera.settings?.require_vest
    if (!camera.settings || !observation || obscured || camera.delayed)
      return { label: 'Нет данных', tone: 'neutral' }
    if (!required) return { label: 'Не требуется', tone: 'neutral' }
    if (!observation.people.length) return { label: 'Нет людей', tone: 'neutral' }
    if (
      observation.alerts.some(
        (alert) => alert.code === 'ppe_required' && alert.missing.includes(kind),
      )
    )
      return { label: 'Не обнаружен' + (kind === 'helmet' ? 'а' : ''), tone: 'missing' }
    if (observation.people.some((person) => person[kind] === 'not_detected'))
      return { label: 'Проверяем отсутствие', tone: 'pending' }
    if (
      observation.people.some(
        (person) => person[kind] === 'uncertain' || person[kind] === 'unavailable',
      )
    )
      return { label: 'Не различим' + (kind === 'helmet' ? 'а' : ''), tone: 'neutral' }
    return { label: 'Обнаружен' + (kind === 'helmet' ? 'а' : ''), tone: 'present' }
  }
  const zonePoints = editing
    ? points
    : !camera.stream
      ? []
      : (zone?.points ??
        (zone
          ? [
              [zone.left, zone.top],
              [zone.right, zone.top],
              [zone.right, zone.bottom],
              [zone.left, zone.bottom],
            ]
          : []))
  useEffect(() => {
    if (camera.settings) setDraft(camera.settings)
  }, [camera.settings])
  useEffect(() => {
    const element = viewport.current
    if (!element) return
    const resize = () => {
      const width = Math.min(element.clientWidth, element.clientHeight * ratio)
      setSize({ width, height: width / ratio })
    }
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    resize()
    return () => observer.disconnect()
  }, [ratio])
  async function save() {
    if (editing && points.length !== 4) return
    let next = draft
    if (editing)
      next = {
        ...draft,
        danger_zone: {
          name: draft.danger_zone?.name || 'Опасная зона',
          points,
          left: Math.min(...points.map((p) => p[0])),
          right: Math.max(...points.map((p) => p[0])),
          top: Math.min(...points.map((p) => p[1])),
          bottom: Math.max(...points.map((p) => p[1])),
        },
      }
    if (await camera.saveSettings(next)) {
      setSaved(true)
      setEditing(false)
    }
  }
  const startDrawing = () => {
    setEditing(true)
    setPoints([])
    setSaved(false)
    setPanel(false)
  }
  const status = !connected
    ? 'Превью выключено'
    : camera.phase === 'starting'
      ? 'Подключение камеры'
      : obscured
        ? 'Изображение неразличимо'
        : camera.delayed
          ? 'Нет свежего результата'
          : observation
            ? 'Прямой эфир'
            : 'Подготовка модели'
  return (
    <section className="surveillance v2" aria-label="Видеонаблюдение">
      <header className="v2-heading">
        <span className="eyebrow">ВИДЕОНАБЛЮДЕНИЕ</span>
        <h1>Эфир</h1>
        <p>Прямой поток с камеры и результаты обнаружения.</p>
      </header>
      <div className="surveillance-toolbar">
        <span>
          <Camera size={17} /> Камера ноутбука
        </span>
        <div className="surveillance-actions">
          {editing && (
            <>
              <button className="stage-button" onClick={() => setPoints(points.slice(0, -1))}>
                Отменить точку
              </button>
              <button
                className="stage-button start"
                disabled={points.length !== 4 || camera.saving}
                onClick={() => void save()}
              >
                Сохранить зону
              </button>
              <button className="stage-button" onClick={() => setEditing(false)}>
                Отмена
              </button>
            </>
          )}
          <button className="stage-button" onClick={() => setPanel(!panel)} aria-expanded={panel}>
            <Settings2 size={16} /> Зона и СИЗ
          </button>
          <button
            className="stage-button"
            aria-label="Полный экран"
            onClick={() => {
              if (document.fullscreenElement) void document.exitFullscreen()
              else void viewport.current?.parentElement?.requestFullscreen()
            }}
          >
            <Expand size={16} />
          </button>
          {connected ? (
            <button className="stage-button start" onClick={() => camera.stop()}>
              <Square size={14} /> Остановить
            </button>
          ) : (
            <button
              className="stage-button start"
              disabled={!modelAvailable || blocked}
              onClick={() => void camera.start()}
            >
              <Camera size={16} /> Включить превью
            </button>
          )}
        </div>
      </div>
      <div className="v2-live-grid">
        <div className="surveillance-stage">
          <button
            className="exit-stage-fullscreen stage-button"
            aria-label="Выйти из полного экрана"
            onClick={() => void document.exitFullscreen()}
          >
            <Expand size={16} /> Выйти из полного экрана
          </button>
          <div className="surveillance-viewport" ref={viewport}>
            <div className="live-surface" style={size}>
              <video
                ref={camera.videoRef}
                autoPlay
                playsInline
                muted
                onLoadedMetadata={() => {
                  const v = camera.videoRef.current
                  if (v?.videoWidth) setRatio(v.videoWidth / v.videoHeight)
                }}
              />
              <svg
                className={`live-overlay ${editing ? 'drawing' : ''}`}
                viewBox={`0 0 ${size.width} ${size.height}`}
                aria-label="Обнаружения и опасная зона"
                onPointerDown={(e) => {
                  if (!editing || points.length === 4) return
                  const b = e.currentTarget.getBoundingClientRect()
                  setPoints([
                    ...points,
                    [
                      Math.max(0, Math.min(1, (e.clientX - b.left) / b.width)),
                      Math.max(0, Math.min(1, (e.clientY - b.top) / b.height)),
                    ],
                  ])
                }}
              >
                <g className={`danger-area ${editing ? 'draft' : ''}`}>
                  {zonePoints.length > 1 && (
                    <polygon
                      points={zonePoints
                        .map((p) => `${p[0] * size.width},${p[1] * size.height}`)
                        .join(' ')}
                    />
                  )}
                  {zonePoints.map((p, i) => (
                    <g key={i}>
                      <circle cx={p[0] * size.width} cy={p[1] * size.height} r={5} />
                      <text x={p[0] * size.width + 10} y={p[1] * size.height - 8}>
                        {i + 1}
                      </text>
                    </g>
                  ))}
                </g>
                <DetectionBoxes
                  objects={observation?.detections ?? []}
                  width={size.width}
                  height={size.height}
                />
              </svg>
            </div>
          </div>
          {!camera.stream && (
            <div className="live-empty">
              <div className="camera-glyph">
                <Camera size={38} />
              </div>
              <h2>Камера ноутбука</h2>
              <p>
                Включите видео, задайте зону четырьмя точками
                <br />и выберите обязательные СИЗ.
              </p>
              <button
                className="stage-button start"
                disabled={!modelAvailable || blocked}
                onClick={() => void camera.start()}
              >
                Включить камеру
              </button>
            </div>
          )}
          <div className="live-status">
            <i className={camera.phase === 'running' && !obscured && !camera.delayed ? 'on' : ''} />
            {status}
          </div>
          {camera.message && (
            <div className="stage-error" role="alert">
              {camera.message}
            </div>
          )}
          {preview.blocked && camera.stream && (
            <div className="playback-prompt">
              <button className="stage-button start" onClick={preview.resume}>
                Показать изображение
              </button>
            </div>
          )}
          {editing && (
            <div className="drawing-instruction">
              Нажмите 4 угла по порядку вдоль границы · {points.length}/4. Затем сохраните зону.
            </div>
          )}
          {obscured && (
            <div className="camera-health-alert" role="alert">
              <AlertTriangle />
              <strong>Камера закрыта или кадр неразличим</strong>
              <p>
                Проверьте объектив и освещение.{' '}
                {Math.floor(observation?.camera_health_seconds ?? 0)} с
              </p>
            </div>
          )}
          {camera.delayed && (
            <div className="camera-health-alert" role="alert">
              <AlertTriangle />
              <strong>Нет свежих кадров</strong>
              <p>Проверьте камеру и соединение. Контроль приостановлен.</p>
            </div>
          )}
          <div className="live-footer">
            <span>
              {obscured
                ? 'Нет данных о людях'
                : observation
                  ? `${observation.people_total} чел.`
                  : 'Нет данных'}
            </span>
            <span>{camera.roundtrip !== null ? `${camera.roundtrip} мс` : 'Без звука'}</span>
            <button onClick={onAll}>
              Журнал <span>{events.length}</span>
            </button>
          </div>
        </div>
        <aside className="v2-side">
          {panel ? (
            <section className="surveillance-settings" aria-label="Зона и СИЗ">
              <div className="settings-heading">
                <h2>Зона и СИЗ</h2>
                <button aria-label="Закрыть настройки" onClick={() => setPanel(false)}>
                  <X size={18} />
                </button>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  void save()
                }}
              >
                <label>
                  Устройство
                  <select
                    value={camera.deviceId}
                    disabled={connected}
                    onChange={(e) => camera.setDeviceId(e.target.value)}
                  >
                    <option value="">Системная камера</option>
                    {camera.devices
                      .filter((d) => d.deviceId)
                      .map((d) => (
                        <option key={d.deviceId} value={d.deviceId}>
                          {d.label || 'Камера'}
                        </option>
                      ))}
                  </select>
                </label>
                <fieldset>
                  <legend>СИЗ во всём кадре</legend>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={draft.require_helmet}
                      onChange={(e) => {
                        setSaved(false)
                        setDraft({ ...draft, require_helmet: e.target.checked })
                      }}
                    />
                    Каска обязательна
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={draft.require_vest}
                      onChange={(e) => {
                        setSaved(false)
                        setDraft({ ...draft, require_vest: e.target.checked })
                      }}
                    />
                    Жилет обязателен
                  </label>
                </fieldset>
                <fieldset>
                  <legend>Опасная зона</legend>
                  <p>{zone ? 'Зона сохранена' : 'Зона не задана'}</p>
                  <button type="button" className="stage-button" onClick={startDrawing}>
                    Выделить на видео
                  </button>
                  {draft.danger_zone && (
                    <>
                      <label>
                        Название
                        <input
                          value={draft.danger_zone.name}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              danger_zone: { ...draft.danger_zone!, name: e.target.value },
                            })
                          }
                        />
                      </label>
                      <button
                        type="button"
                        onClick={() => {
                          setDraft({ ...draft, danger_zone: null })
                          setSaved(false)
                        }}
                      >
                        Удалить зону при сохранении
                      </button>
                    </>
                  )}
                  <p className="settings-hint">
                    Четыре угла зоны. Любое пересечение рамки человека с зоной считается входом,
                    включая касание границы.
                  </p>
                </fieldset>
                <button
                  className="save-zone"
                  disabled={camera.saving || (editing && points.length !== 4)}
                >
                  Сохранить настройки
                </button>
                {saved && (
                  <p className="saved-note" role="status">
                    Настройки сохранены
                  </p>
                )}
              </form>
            </section>
          ) : (
            <section className="v2-summary" aria-label="Контроль каски и жилета">
              <h2>Контроль в кадре</h2>
              <dl>
                <div>
                  <dt>Люди сейчас</dt>
                  <dd>{!obscured && observation ? observation.people_total : '—'}</dd>
                </div>
                {(['helmet', 'vest'] as const).map((kind) => {
                  const status = gearStatus(kind)
                  return (
                    <div key={kind}>
                      <dt>{kind === 'helmet' ? 'Каски' : 'Жилеты'}</dt>
                      <dd className="gear-result">
                        <span>
                          {!obscured && observation
                            ? observation.detections.filter((d) => d.kind === kind).length
                            : '—'}
                        </span>
                        <small className={`ppe-${status.tone}`}>{status.label}</small>
                      </dd>
                    </div>
                  )
                })}
                <div>
                  <dt>Опасная зона</dt>
                  <dd>{zone ? 'Включена' : 'Не задана'}</dd>
                </div>
              </dl>
              <button className="stage-button" onClick={startDrawing}>
                Задать 4 точки
              </button>
              <p>
                Восстановление номера — до 3 секунд. В счётчике только люди, обнаруженные в текущем
                кадре.
              </p>
            </section>
          )}
          <section
            className="video-alert-feed"
            aria-label="Предупреждения поверх видео"
            role="log"
            aria-live="polite"
          >
            {(observation?.alerts ?? []).map((a) => (
              <article key={a.id} className={`video-alert ${a.severity}`}>
                <AlertTriangle size={18} />
                <div>
                  <strong>{a.message}</strong>
                  <p>
                    {a.code === 'danger_zone'
                      ? a.zone
                      : a.missing.map((k) => (k === 'helmet' ? 'Каска' : 'Жилет')).join(', ')}
                  </p>
                  <small>
                    Человек · {a.track_id} · {Math.floor(a.duration_seconds)} с
                  </small>
                </div>
              </article>
            ))}
            {!observation?.alerts.length && (
              <p className="v2-current-state">
                {obscured || camera.delayed
                  ? 'Контроль недоступен'
                  : observation?.pending_signals
                    ? 'Перепроверяем сигнал по нескольким кадрам…'
                    : observation?.uncertain
                      ? 'Часть СИЗ неразличима. Нужен более чёткий кадр.'
                      : observation
                        ? 'Текущих подтверждённых тревог нет'
                        : 'Ожидаем изображение'}
              </p>
            )}
          </section>
        </aside>
      </div>
    </section>
  )
}
