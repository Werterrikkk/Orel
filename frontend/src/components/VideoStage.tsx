import { useEffect, useRef, useState, type RefObject } from 'react'
import { Maximize2, Minimize2, Pause, Play, RotateCcw, ScanLine, Upload } from 'lucide-react'
import { mediaTime } from '../api'
import type { Analysis, Box, Video, Zone } from '../types'

interface Props {
  video: Video | null
  analysis: Analysis | null
  zone: Zone | null
  editing: boolean
  busy: boolean
  videoRef: RefObject<HTMLVideoElement | null>
  onDraw: (box: Box) => void
  onUpload: () => void
  onPlayback: () => void
  onSeek: () => void
}

export function VideoStage({
  video,
  analysis,
  zone,
  editing,
  busy,
  videoRef,
  onDraw,
  onUpload,
  onPlayback,
  onSeek,
}: Props) {
  const viewport = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 450 })
  const [position, setPosition] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [mediaError, setMediaError] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [drag, setDrag] = useState<Box | null>(null)
  const pointerStart = useRef<[number, number] | null>(null)
  useEffect(() => {
    const changed = () =>
      setFullscreen(document.fullscreenElement === viewport.current?.parentElement)
    document.addEventListener('fullscreenchange', changed)
    return () => document.removeEventListener('fullscreenchange', changed)
  }, [])
  useEffect(() => {
    setPosition(0)
    setPlaying(false)
    setMediaError(false)
  }, [video?.id])
  useEffect(() => {
    const element = viewport.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      const ratio = video ? video.width / video.height : 16 / 9
      const width = Math.min(entry.contentRect.width, entry.contentRect.height * ratio)
      setDimensions({ width, height: width / ratio })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [video])
  useEffect(() => {
    if (editing) videoRef.current?.pause()
  }, [editing, videoRef])
  const latestSample = analysis?.frames.findLast((frame) => frame.time <= position)
  const sample =
    !mediaError &&
    latestSample &&
    analysis &&
    position - latestSample.time <= Math.max(0.75, 2 / analysis.sample_fps)
      ? latestSample
      : null
  const displayZone = drag
    ? {
        left: Math.min(drag[0], drag[2]),
        top: Math.min(drag[1], drag[3]),
        right: Math.max(drag[0], drag[2]),
        bottom: Math.max(drag[1], drag[3]),
      }
    : zone
  const normalizedPoint = (event: React.PointerEvent<SVGSVGElement>): [number, number] => {
    const rectangle = event.currentTarget.getBoundingClientRect()
    return [
      Math.max(0, Math.min(1, (event.clientX - rectangle.left) / rectangle.width)),
      Math.max(0, Math.min(1, (event.clientY - rectangle.top) / rectangle.height)),
    ]
  }
  async function togglePlay() {
    const element = videoRef.current
    if (!element) return
    try {
      if (element.paused) await element.play()
      else element.pause()
    } catch {
      setMediaError(true)
    }
  }

  return (
    <section className="video-panel" aria-label="Просмотр видео">
      <div className="panel-bar">
        <span>
          <span className={`source-dot ${playing ? 'on' : ''}`} />
          {video ? 'ЗАПИСЬ / 01' : 'ИСТОЧНИК НЕ ПОДКЛЮЧЁН'}
        </span>
        <span className="mono">
          {video ? `${video.width} × ${video.height}` : 'MP4 · MOV · WEBM'}
        </span>
      </div>
      <div className={`video-viewport ${editing ? 'is-editing' : ''}`} ref={viewport}>
        {!video ? (
          <div className="empty-video">
            <div className="viewfinder">
              <ScanLine size={36} strokeWidth={1.2} />
            </div>
            <h2>Начните с видеозаписи</h2>
            <p>
              Загрузите короткий ролик с рабочей зоны.
              <br />
              Видео обрабатывается на этом компьютере.
            </p>
            <button className="button light" disabled={busy} onClick={onUpload}>
              <Upload size={16} /> Выбрать видео
            </button>
            <span className="empty-hint">До 200 МБ · до 10 минут · рекомендуем MP4 H.264</span>
          </div>
        ) : (
          <div className="video-surface" style={dimensions}>
            <video
              key={video.id}
              ref={videoRef}
              src={video.media_url}
              poster={video.preview_url}
              muted
              playsInline
              preload="auto"
              onTimeUpdate={() => {
                setPosition(videoRef.current?.currentTime ?? 0)
                onPlayback()
              }}
              onPlay={() => {
                setPlaying(true)
                onPlayback()
              }}
              onPause={() => {
                setPlaying(false)
                onPlayback()
              }}
              onEnded={() => {
                setPlaying(false)
                onPlayback()
              }}
              onError={() => setMediaError(true)}
              onSeeking={onSeek}
              onSeeked={() => {
                setPosition(videoRef.current?.currentTime ?? 0)
                onPlayback()
              }}
            />
            <svg
              className={`video-overlay ${editing ? 'drawing' : ''}`}
              viewBox="0 0 1000 1000"
              preserveAspectRatio="none"
              aria-label="Область выделения зоны"
              onPointerDown={(event) => {
                if (!editing) return
                event.preventDefault()
                event.currentTarget.setPointerCapture(event.pointerId)
                pointerStart.current = normalizedPoint(event)
                setDrag([...pointerStart.current, ...pointerStart.current])
              }}
              onPointerMove={(event) => {
                if (pointerStart.current)
                  setDrag([...pointerStart.current, ...normalizedPoint(event)])
              }}
              onPointerCancel={() => {
                pointerStart.current = null
                setDrag(null)
              }}
              onPointerUp={(event) => {
                if (!pointerStart.current) return
                const [x, y] = normalizedPoint(event)
                const [sx, sy] = pointerStart.current
                pointerStart.current = null
                setDrag(null)
                if (Math.abs(x - sx) > 0.025 && Math.abs(y - sy) > 0.025)
                  onDraw([Math.min(sx, x), Math.min(sy, y), Math.max(sx, x), Math.max(sy, y)])
              }}
            >
              {displayZone && (
                <rect
                  x={displayZone.left * 1000}
                  y={displayZone.top * 1000}
                  width={(displayZone.right - displayZone.left) * 1000}
                  height={(displayZone.bottom - displayZone.top) * 1000}
                  className="zone-rect"
                />
              )}
              {!editing &&
                sample?.objects.map((item, index) => {
                  const [x1, y1, x2, y2] = item.box
                  return (
                    <g key={index} className={`detection ${item.kind}`}>
                      <rect
                        x={x1 * 1000}
                        y={y1 * 1000}
                        width={(x2 - x1) * 1000}
                        height={(y2 - y1) * 1000}
                      />
                      {item.kind === 'person' && (
                        <circle cx={(x1 + x2) * 500} cy={y2 * 1000} r="5" />
                      )}
                    </g>
                  )
                })}
            </svg>
          </div>
        )}
        {editing && (
          <span className="drawing-hint">Потяните мышью по кадру, чтобы выделить зону</span>
        )}
        {video?.status === 'processing' && (
          <div className="processing-overlay">
            <div className="spinner" />
            <strong>Анализируем запись</strong>
            <span>{Math.round(video.progress * 100)}%</span>
            <progress value={video.progress} max="1" />
          </div>
        )}
        {mediaError && (
          <div className="media-error" role="alert">
            Браузер не смог воспроизвести видео. Загрузите MP4 с кодеком H.264.
          </div>
        )}
      </div>
      <div className="video-controls">
        <button
          className="icon-button"
          aria-label={playing ? 'Пауза' : 'Воспроизвести'}
          disabled={!video || editing || mediaError || video.status === 'processing'}
          onClick={() => void togglePlay()}
        >
          {playing ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <button
          className="icon-button"
          aria-label="В начало"
          disabled={!video}
          onClick={() => {
            if (videoRef.current) {
              videoRef.current.currentTime = 0
              setPosition(0)
              onPlayback()
            }
          }}
        >
          <RotateCcw size={16} />
        </button>
        <span className="mono playback-time">
          {mediaTime(position)} <span>/ {mediaTime(video?.duration ?? 0)}</span>
        </span>
        <input
          aria-label="Позиция видео"
          type="range"
          min="0"
          max={video?.duration ?? 1}
          step="0.05"
          value={position}
          disabled={!video || editing}
          onChange={(event) => {
            const value = Number(event.target.value)
            setPosition(value)
            if (videoRef.current) {
              videoRef.current.currentTime = value
              onPlayback()
            }
          }}
        />
        <button
          className="icon-button"
          aria-label={fullscreen ? 'Свернуть видео' : 'Полный экран'}
          disabled={!video}
          onClick={() => {
            const action = fullscreen
              ? document.exitFullscreen()
              : viewport.current?.parentElement?.requestFullscreen()
            void action?.catch(() => {})
          }}
        >
          {fullscreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
        </button>
      </div>
    </section>
  )
}
