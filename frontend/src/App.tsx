import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Camera, CircleHelp, Cpu, Radio, X } from 'lucide-react'
import { api, ApiError, localTime } from './api'
import type { Bootstrap, CameraSource, SafetyEvent } from './types'
import { CameraWorkspace } from './components/CameraWorkspace'
import { EventDetails, EventJournal } from './components/EventJournal'
import { Sidebar, type ConsolePage } from './components/Sidebar'
import { TelegramSettings } from './components/TelegramSettings'

export default function App() {
  const [page, setPage] = useState<ConsolePage>('camera')
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null)
  const [sources, setSources] = useState<CameraSource[]>([])
  const [events, setEvents] = useState<SafetyEvent[]>([])
  const [selected, setSelected] = useState<SafetyEvent | null>(null)
  const [error, setError] = useState('')
  const [help, setHelp] = useState(false)
  const [clock, setClock] = useState(new Date())
  const alive = useRef(true)
  const refreshEvents = useCallback(async () => {
    try {
      const list = await api<SafetyEvent[]>('/events', { signal: AbortSignal.timeout(3000) })
      if (alive.current) setEvents(list)
    } catch (value) {
      if (alive.current) setError(value instanceof Error ? value.message : 'Журнал недоступен.')
    }
  }, [])
  useEffect(() => {
    alive.current = true
    let loading = false
    const load = async () => {
      if (loading) return
      loading = true
      try {
        const [data, list, adapters] = await Promise.all([
          api<Bootstrap>('/bootstrap', { signal: AbortSignal.timeout(3000) }),
          api<SafetyEvent[]>('/events', { signal: AbortSignal.timeout(3000) }),
          api<CameraSource[]>('/sources', { signal: AbortSignal.timeout(3000) }),
        ])
        if (alive.current) {
          setBootstrap(data)
          setEvents(list)
          setSources(adapters)
          setError('')
        }
      } catch (value) {
        if (alive.current)
          setError(
            value instanceof ApiError && value.status === 404
              ? 'Запущена старая версия сервера. Перезапустите приложение через scripts/start.sh.'
              : value instanceof Error
                ? value.message
                : 'Нет связи с приложением.',
          )
      } finally {
        loading = false
      }
    }
    void load()
    const polling = setInterval(() => void load(), 3000)
    const time = setInterval(() => setClock(new Date()), 1000)
    return () => {
      alive.current = false
      clearInterval(polling)
      clearInterval(time)
    }
  }, [])
  async function reviewEvent(event: SafetyEvent) {
    try {
      const result = await api<SafetyEvent>(`/events/${event.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ reviewed: !event.reviewed }),
      })
      setSelected((current) => (current?.id === event.id ? result : current))
      await refreshEvents()
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Не удалось сохранить отметку.')
    }
  }
  return (
    <div className="console-shell">
      <Sidebar
        page={page}
        pending={events.filter((event) => !event.reviewed).length}
        onPage={setPage}
        onHelp={() => setHelp(true)}
      />
      <main className={`console-main ${page === 'camera' ? 'is-live' : ''}`}>
        {error && (
          <div className="console-error" role="alert">
            {error}
            <button aria-label="Скрыть ошибку" onClick={() => setError('')}>
              <X size={15} />
            </button>
          </div>
        )}
        {page === 'camera' && (
          <CameraWorkspace
            modelAvailable={bootstrap?.models.ppe.available ?? false}
            blocked={bootstrap?.videos.some((video) => video.status === 'processing') ?? false}
            events={events.filter((event) => event.source_type === 'camera')}
            onEvents={() => void refreshEvents()}
            onSelect={setSelected}
            onAll={() => setPage('events')}
          />
        )}
        {page === 'notifications' && <TelegramSettings />}
        {page === 'events' && (
          <div className="console-page">
            <header className="console-page-heading">
              <div>
                <span className="eyebrow">КОНТРОЛЬ БЕЗОПАСНОСТИ</span>
                <h1>Журнал событий</h1>
                <p>Сигналы с камер и отметки оператора.</p>
              </div>
              <time>{localTime(clock.toISOString())} МСК</time>
            </header>
            <EventJournal events={events} onSelect={setSelected} />
          </div>
        )}
        {page === 'settings' && (
          <div className="console-page">
            <header className="console-page-heading">
              <div>
                <span className="eyebrow">ПОДКЛЮЧЕНИЕ</span>
                <h1>Камеры</h1>
                <p>Источник изображения и место обработки.</p>
              </div>
            </header>
            <div className="source-cards">
              {sources.map((source) => (
                <section
                  className={`source-card device-card ${source.available ? 'device-local' : 'device-remote'}`}
                  key={source.id}
                >
                  <img
                    className="device-backdrop"
                    src={source.available ? '/devices/macbook.png' : '/devices/rubetek.png'}
                    alt=""
                    aria-hidden="true"
                  />
                  <div className="source-card-title">
                    <Camera size={22} />
                    <span className={`source-badge ${source.available ? 'ready' : ''}`}>
                      {source.available ? 'Доступна для превью' : 'Ожидает подключения'}
                    </span>
                  </div>
                  <h2>{source.name}</h2>
                  <p>{source.detail}</p>
                  <dl>
                    <div>
                      <dt>Обработка</dt>
                      <dd>{source.available ? 'На ноутбуке' : 'На камере · планируется'}</dd>
                    </div>
                    <div>
                      <dt>Подключение</dt>
                      <dd>{source.available ? 'Камера браузера' : 'API / SDK производителя'}</dd>
                    </div>
                  </dl>
                  {source.available ? (
                    <button className="button" onClick={() => setPage('camera')}>
                      Открыть превью <ArrowUpRight size={15} />
                    </button>
                  ) : (
                    <p className="source-footnote">
                      Для интеграции нужны модель камеры, SDK, формат модели для её ускорителя и API
                      видеопотока/обнаружений.
                    </p>
                  )}
                </section>
              ))}
            </div>
            <section className="model-note">
              <Cpu size={20} />
              <div>
                <h2>YOLO26n · люди, каски и жилеты</h2>
                <p>
                  {bootstrap?.models.ppe.available
                    ? 'Обученные веса подключены. Повторное обучение не требуется.'
                    : 'Подключите сохранённую модель СИЗ.'}{' '}
                  Результаты нужно проверять на выбранной камере.
                </p>
              </div>
            </section>
            <section className="source-explainer">
              <Radio size={20} />
              <div>
                <h2>Одна логика для разных источников</h2>
                <p>
                  Сейчас кадры обрабатывает ноутбук. Для Rubetek предусмотрен отдельный адаптер
                  обнаружений. Правила зон, таймеры предупреждений и интерфейс от источника не
                  зависят.
                </p>
              </div>
            </section>
          </div>
        )}
      </main>
      {selected && (
        <EventDetails
          event={selected}
          onClose={() => setSelected(null)}
          onReview={() => reviewEvent(selected)}
        />
      )}
      {help && (
        <div className="dialog-backdrop" onClick={() => setHelp(false)}>
          <section
            className="console-help"
            role="dialog"
            aria-modal="true"
            aria-labelledby="help-title"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="help-close"
              aria-label="Закрыть справку"
              autoFocus
              onClick={() => setHelp(false)}
            >
              <X size={20} />
            </button>
            <CircleHelp size={24} />
            <h2 id="help-title">Как работает контроль</h2>
            <p>
              Включите превью и разрешите камеру. Голова и торс должны полностью попадать в кадр.
            </p>
            <p>
              В «Зона и СИЗ» выберите обязательную экипировку и выделите опасный участок. СИЗ
              проверяются во всём кадре.
            </p>
            <p>
              Сигнал подтверждается минимум шестью наблюдениями за две секунды. Красный уровень —
              после 10 секунд наблюдения. Потеря кадра или неоднозначное совпадение рамок сбрасывает
              таймер. Номер рамки не устанавливает личность.
            </p>
            <p>
              Камера отключается при уходе из видеонаблюдения или переходе вкладки в фон. Микрофон
              не используется. Сохраняются только кадры событий.
            </p>
          </section>
        </div>
      )}
    </div>
  )
}
