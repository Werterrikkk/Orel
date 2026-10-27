import { useEffect, useState } from 'react'
import { Check, FileCheck2, Pencil, SquareDashed, X } from 'lucide-react'
import type { Configuration, Permit, Zone } from '../types'

interface Props {
  config: Configuration | null
  zoneDraft: Zone
  editing: boolean
  busy: boolean
  now: number
  onDraft: (zone: Zone) => void
  onEdit: () => void
  onCancel: () => void
  onSaveZone: () => Promise<void>
  onSavePermit: (permit: Permit) => Promise<void>
  onClosePermit: () => Promise<void>
}

function inputTime(value: Date) {
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Europe/Moscow',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
    .format(value)
    .replace(' ', 'T')
}

export function ConfigurationPanel({
  config,
  zoneDraft,
  editing,
  busy,
  now,
  onDraft,
  onEdit,
  onCancel,
  onSaveZone,
  onSavePermit,
  onClosePermit,
}: Props) {
  const [permitEditing, setPermitEditing] = useState(false)
  const [number, setNumber] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [validation, setValidation] = useState('')
  const permit = config?.permit
  useEffect(() => {
    setNumber(permit?.number ?? '')
    setStart(inputTime(permit ? new Date(permit.starts_at) : new Date(Date.now() - 30 * 60_000)))
    setEnd(inputTime(permit ? new Date(permit.ends_at) : new Date(Date.now() + 60 * 60_000)))
    setPermitEditing(false)
    setValidation('')
  }, [config?.video_id, permit])
  const state = !permit
    ? 'Не задан'
    : permit.closed
      ? 'Закрыт'
      : now < Date.parse(permit.starts_at)
        ? 'Ожидает начала'
        : now >= Date.parse(permit.ends_at)
          ? 'Срок истёк'
          : 'Действует'
  const active = state === 'Действует'
  const validZone = zoneDraft.left < zoneDraft.right && zoneDraft.top < zoneDraft.bottom

  return (
    <aside className="configuration-panel">
      <section className="config-section">
        <div className="section-title">
          <h2>
            <SquareDashed size={17} /> Рабочая зона
          </h2>
          {config?.zone && !editing && (
            <button
              className="icon-button"
              aria-label="Изменить зону"
              disabled={busy}
              onClick={onEdit}
            >
              <Pencil size={15} />
            </button>
          )}
        </div>
        {editing ? (
          <div className="zone-form">
            <label>
              Название зоны
              <input
                value={zoneDraft.name}
                maxLength={100}
                onChange={(event) => onDraft({ ...zoneDraft, name: event.target.value })}
              />
            </label>
            <p className="field-help">
              Выделите участок на кадре. Человек считается в зоне, если внутри точка под его ногами.
            </p>
            <details className="zone-coordinates">
              <summary>Границы зоны, % кадра</summary>
              <div>
                {(
                  [
                    ['left', 'Слева'],
                    ['top', 'Сверху'],
                    ['right', 'Справа'],
                    ['bottom', 'Снизу'],
                  ] as const
                ).map(([edge, label]) => (
                  <label key={edge}>
                    {label}, %
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                      value={Math.round(zoneDraft[edge] * 1000) / 10}
                      onChange={(event) =>
                        onDraft({
                          ...zoneDraft,
                          [edge]: Math.max(0, Math.min(100, Number(event.target.value))) / 100,
                        })
                      }
                    />
                  </label>
                ))}
              </div>
            </details>
            {!validZone && (
              <p className="inline-error" role="alert">
                Правая граница должна быть правее левой, а нижняя — ниже верхней.
              </p>
            )}
            <span className="field-label">Обязательные СИЗ</span>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={zoneDraft.require_helmet}
                onChange={(event) =>
                  onDraft({
                    ...zoneDraft,
                    require_helmet: event.target.checked,
                  })
                }
              />{' '}
              Защитная каска
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={zoneDraft.require_vest}
                onChange={(event) => onDraft({ ...zoneDraft, require_vest: event.target.checked })}
              />{' '}
              Сигнальный жилет
            </label>
            <div className="button-row">
              <button
                className="button primary compact"
                disabled={busy || !zoneDraft.name.trim() || !validZone}
                onClick={() => void onSaveZone()}
              >
                <Check size={15} /> Сохранить
              </button>
              <button className="button compact" disabled={busy} onClick={onCancel}>
                Отмена
              </button>
            </div>
          </div>
        ) : config?.zone ? (
          <>
            <p className="zone-name">
              <span className="zone-swatch" />
              {config.zone.name}
            </p>
            <div className="requirements">
              <span className={config.zone.require_helmet ? 'required' : ''}>
                Каска {config.zone.require_helmet ? 'обязательна' : 'не требуется'}
              </span>
              <span className={config.zone.require_vest ? 'required' : ''}>
                Жилет {config.zone.require_vest ? 'обязателен' : 'не требуется'}
              </span>
            </div>
          </>
        ) : (
          <>
            <p className="muted-description">
              Выделите участок на кадре для проверки присутствия людей.
            </p>
            <button className="button full" onClick={onEdit} disabled={!config || busy}>
              <SquareDashed size={16} /> Выделить зону
            </button>
          </>
        )}
      </section>
      <section className="config-section permit-section">
        <div className="section-title">
          <h2>
            <FileCheck2 size={17} /> Наряд-допуск
          </h2>
          <span className={`status-label ${active ? 'good' : ''}`}>{state}</span>
        </div>
        {permit && !permitEditing ? (
          <>
            <p className="permit-number">№ {permit.number}</p>
            <dl className="permit-details">
              <div>
                <dt>Начало работ</dt>
                <dd>
                  {new Date(permit.starts_at).toLocaleString('ru-RU', {
                    timeZone: 'Europe/Moscow',
                    day: '2-digit',
                    month: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </dd>
              </div>
              <div>
                <dt>Окончание</dt>
                <dd>
                  {new Date(permit.ends_at).toLocaleString('ru-RU', {
                    timeZone: 'Europe/Moscow',
                    day: '2-digit',
                    month: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </dd>
              </div>
            </dl>
            <div className="button-row">
              <button
                className="button compact"
                disabled={busy}
                onClick={() => setPermitEditing(true)}
              >
                <Pencil size={14} /> Изменить
              </button>
              {!permit.closed && (
                <button
                  className="button compact danger-outline"
                  disabled={busy}
                  onClick={() => void onClosePermit()}
                >
                  <X size={14} /> Закрыть наряд
                </button>
              )}
            </div>
          </>
        ) : permitEditing ? (
          <form
            onSubmit={(event) => {
              event.preventDefault()
              const starts = new Date(`${start}:00+03:00`),
                ends = new Date(`${end}:00+03:00`)
              if (
                !number.trim() ||
                !Number.isFinite(starts.getTime()) ||
                !Number.isFinite(ends.getTime()) ||
                ends <= starts
              ) {
                setValidation('Укажите номер. Окончание должно быть позже начала.')
                return
              }
              setValidation('')
              void onSavePermit({
                number: number.trim(),
                starts_at: starts.toISOString(),
                ends_at: ends.toISOString(),
                closed: permit?.closed ?? false,
              })
            }}
          >
            <label>
              Номер наряда
              <input
                value={number}
                maxLength={100}
                placeholder="Например, НД-042"
                onChange={(event) => setNumber(event.target.value)}
                required
              />
            </label>
            <label>
              Начало работ
              <input
                aria-label="Начало работ"
                type="datetime-local"
                value={start}
                onChange={(event) => setStart(event.target.value)}
                required
              />
            </label>
            <label>
              Окончание работ
              <input
                aria-label="Окончание работ"
                type="datetime-local"
                value={end}
                onChange={(event) => setEnd(event.target.value)}
                required
              />
            </label>
            <p className="field-help">
              Время московское, UTC+3.{permit?.closed ? ' Наряд останется закрытым.' : ''}
            </p>
            {validation && (
              <p className="inline-error" role="alert">
                {validation}
              </p>
            )}
            <div className="button-row">
              <button className="button primary compact" disabled={busy} type="submit">
                Сохранить наряд
              </button>
              <button
                className="button compact"
                type="button"
                disabled={busy}
                onClick={() => setPermitEditing(false)}
              >
                Отмена
              </button>
            </div>
          </form>
        ) : (
          <>
            <p className="muted-description">
              Укажите номер и время работ. Присутствие без действующего наряда попадёт в журнал.
            </p>
            <button
              className="button full"
              disabled={!config?.zone || busy}
              onClick={() => setPermitEditing(true)}
            >
              Создать наряд
            </button>
          </>
        )}
      </section>
      <div className="config-note">
        <p>
          Наряд разрешает работы в зоне по расписанию. Допуск конкретного сотрудника здесь не
          проверяется.
        </p>
      </div>
    </aside>
  )
}
