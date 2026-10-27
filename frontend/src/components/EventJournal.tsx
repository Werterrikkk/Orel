import { useEffect, useRef, useState } from 'react'
import { ArrowDownToLine, ArrowUpRight, Check, ClipboardList, Search, X } from 'lucide-react'
import { localDate, localTime, mediaTime } from '../api'
import type { SafetyEvent } from '../types'

interface Props {
  events: SafetyEvent[]
  compact?: boolean
  onSelect: (event: SafetyEvent) => void
  onAll?: () => void
}

export function EventJournal({ events, compact = false, onSelect, onAll }: Props) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [severity, setSeverity] = useState('all')
  const filtered = events.filter(
    (event) =>
      (filter !== 'pending' || !event.reviewed) &&
      (severity === 'all' || event.severity === severity) &&
      `${event.reason} ${event.zone} ${event.permit_number ?? ''} ${event.video_name}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  )
  const visible = compact ? filtered.slice(0, 5) : filtered
  return (
    <section className="journal-panel">
      <div className="journal-heading">
        <div>
          <h2>
            Журнал событий <span className="count-label">{events.length}</span>
          </h2>
          {!compact && <p>Записи о срабатываниях и отметки проверки</p>}
        </div>
        <div className="journal-actions">
          {compact && onAll ? (
            <button className="text-button" onClick={onAll}>
              Все события <ArrowUpRight size={15} />
            </button>
          ) : (
            <a className="button compact" href="/api/events.csv">
              <ArrowDownToLine size={15} /> Скачать CSV
            </a>
          )}
        </div>
      </div>
      {!compact && (
        <div className="journal-filters">
          <label className="search-field">
            <Search size={17} />
            <input
              aria-label="Поиск событий"
              value={query}
              placeholder="Поиск по причине, зоне или камере"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <select
            aria-label="Статус проверки"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="all">Все события</option>
            <option value="pending">Требуют проверки</option>
          </select>
          <select
            aria-label="Уровень сигнала"
            value={severity}
            onChange={(event) => setSeverity(event.target.value)}
          >
            <option value="all">Все уровни</option>
            <option value="warning">Жёлтый</option>
            <option value="critical">Красный</option>
          </select>
        </div>
      )}
      <div className="table-scroll" role="region" aria-label="Таблица событий" tabIndex={0}>
        <table className="events-table">
          <thead>
            <tr>
              <th>Время, МСК</th>
              <th>Событие</th>
              <th>Зона / источник</th>
              <th>Уровень</th>
              <th>Статус</th>
              <th>
                <span className="sr-only">Открыть</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((event) => (
              <tr key={event.id}>
                <td className="mono">
                  <span>{localDate(event.created_at)}</span>
                  {localTime(event.created_at)}
                  <small>
                    {event.source_type === 'camera'
                      ? 'Прямой эфир'
                      : `${mediaTime(event.position)} в записи`}
                  </small>
                </td>
                <td>
                  <button className="event-title" onClick={() => onSelect(event)}>
                    {event.reason}
                  </button>
                  <small>{event.video_name}</small>
                </td>
                <td>
                  {event.zone}
                  <small>
                    {event.source_type === 'camera'
                      ? event.code === 'danger_zone'
                        ? 'Опасная зона'
                        : 'Проверка СИЗ'
                      : event.permit_number
                        ? `№ ${event.permit_number}`
                        : 'Наряд не задан'}
                  </small>
                </td>
                <td>
                  <span className={`severity-label ${event.severity ?? ''}`}>
                    {event.severity === 'critical'
                      ? 'Красный · 10 с'
                      : event.severity === 'warning'
                        ? 'Жёлтый'
                        : '—'}
                  </span>
                </td>
                <td>
                  <span className={`review-label ${event.reviewed ? 'reviewed' : ''}`}>
                    {event.reviewed ? 'Проверено' : 'На проверку'}
                  </span>
                </td>
                <td>
                  <button
                    className="icon-button"
                    aria-label={`Открыть событие ${localTime(event.created_at)}`}
                    onClick={() => onSelect(event)}
                  >
                    <ArrowUpRight size={17} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!visible.length && (
        <div className="empty-journal">
          <ClipboardList size={25} strokeWidth={1.4} />
          <div>
            <strong>{events.length ? 'По фильтру ничего не найдено' : 'Событий пока нет'}</strong>
            <p>
              {events.length
                ? 'Попробуйте изменить запрос.'
                : 'Срабатывания сохраняются во время проверки.'}
            </p>
          </div>
        </div>
      )}
    </section>
  )
}

export function EventDetails({
  event,
  onClose,
  onReview,
}: {
  event: SafetyEvent | null
  onClose: () => void
  onReview: (event: SafetyEvent) => Promise<void>
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (event) dialog.current?.showModal()
    else dialog.current?.close()
  }, [event])
  return (
    <dialog
      ref={dialog}
      className="event-dialog"
      aria-labelledby="event-title"
      onCancel={onClose}
      onClick={(click) => {
        if (click.target === dialog.current) onClose()
      }}
    >
      {event && (
        <>
          <div className="dialog-header">
            <div>
              <span className="eyebrow">СОБЫТИЕ / {event.id.slice(0, 8).toUpperCase()}</span>
              <h2 id="event-title">{event.reason}</h2>
            </div>
            <button className="icon-button" onClick={onClose} aria-label="Закрыть событие">
              <X size={20} />
            </button>
          </div>
          <img src={event.snapshot_url} alt={`Кадр события в зоне ${event.zone}`} />
          <dl className="event-metadata">
            <div>
              <dt>Время, МСК</dt>
              <dd>
                {localDate(event.created_at)} {localTime(event.created_at)}
              </dd>
            </div>
            <div>
              <dt>{event.source_type === 'camera' ? 'Источник' : 'Позиция в видео'}</dt>
              <dd>
                {event.source_type === 'camera'
                  ? 'Камера · прямой эфир'
                  : mediaTime(event.position)}
              </dd>
            </div>
            <div>
              <dt>Зона</dt>
              <dd>{event.zone}</dd>
            </div>
            <div>
              <dt>{event.source_type === 'camera' ? 'Уровень' : 'Наряд'}</dt>
              <dd>
                {event.source_type === 'camera'
                  ? event.severity === 'critical'
                    ? 'Красный · 10 секунд'
                    : 'Жёлтый'
                  : (event.permit_number ?? 'Не задан')}
              </dd>
            </div>
          </dl>
          <div className="dialog-footer">
            <p>Снимок первого сигнала. Проверьте кадр перед отметкой.</p>
            <button
              className="button primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                try {
                  await onReview(event)
                } finally {
                  setBusy(false)
                }
              }}
            >
              <Check size={16} />
              {event.reviewed ? 'Вернуть на проверку' : 'Отметить проверенным'}
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}
