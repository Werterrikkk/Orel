import { useEffect, useRef, useState } from 'react'
import { Check, ExternalLink, LoaderCircle, Send } from 'lucide-react'
import { api, localTime } from '../api'
import type { TelegramStatus } from '../types'

type Chat = { id: string; title: string; type: string }
const deliveryLabels = {
  pending: 'В очереди',
  sending: 'Отправляется',
  sent: 'Отправлено',
  failed: 'Ошибка',
  uncertain: 'Доставка не подтверждена',
  expired: 'Устарело',
  cancelled: 'Отменено',
}

export function TelegramSettings() {
  const [status, setStatus] = useState<TelegramStatus | null>(null)
  const [token, setToken] = useState('')
  const [chatId, setChatId] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [chats, setChats] = useState<Chat[] | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const [notice, setNotice] = useState('')
  const initialized = useRef(false)
  const revision = useRef(0)

  useEffect(() => {
    let active = true,
      loading = false
    const load = async () => {
      if (loading) return
      loading = true
      const version = revision.current
      try {
        const data = await api<TelegramStatus>('/telegram', { signal: AbortSignal.timeout(3000) })
        if (!active || version !== revision.current) return
        setStatus(data)
        setConnectionError('')
        if (!initialized.current) {
          initialized.current = true
          setChatId(data.chat_id)
          setEnabled(data.enabled)
        }
      } catch (value) {
        if (active)
          setConnectionError(value instanceof Error ? value.message : 'Настройки недоступны.')
      } finally {
        loading = false
      }
    }
    void load()
    const interval = setInterval(() => void load(), 5000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [])

  async function perform(name: string, work: () => Promise<void>) {
    setBusy(name)
    setError('')
    setNotice('')
    revision.current++
    try {
      await work()
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Не удалось выполнить действие.')
    } finally {
      revision.current++
      setBusy('')
    }
  }

  return (
    <div className="console-page telegram-page">
      <header className="console-page-heading">
        <div>
          <span className="eyebrow">УВЕДОМЛЕНИЯ</span>
          <h1>Telegram</h1>
          <p>Подтверждённые события с камеры — в выбранный чат.</p>
        </div>
        <span className={`telegram-state ${status?.enabled ? 'on' : ''}`}>
          {status?.enabled ? 'Уведомления включены' : 'Уведомления выключены'}
        </span>
      </header>
      {(error || connectionError || status?.queue_error) && (
        <div className="telegram-error" role="alert">
          {error || connectionError || status?.queue_error}
        </div>
      )}
      {notice && (
        <div className="telegram-notice" role="status">
          <Check size={16} />
          {notice}
        </div>
      )}
      <div className="telegram-grid">
        <section className="telegram-card">
          <div className="telegram-step">
            01 <h2>Подключите бота</h2>
          </div>
          <p>
            Откройте{' '}
            <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">
              @BotFather <ExternalLink size={12} />
            </a>
            , отправьте <code>/newbot</code> и задайте имя и уникальный username, заканчивающийся на{' '}
            <code>bot</code>.
          </p>
          <p>
            Полученный токен вставьте здесь. Он сохранится на этом компьютере; после подключения
            поле очистится.
          </p>
          {status?.configured && (
            <div className="connected-bot">
              <Check size={15} />
              Подключён @{status.bot_username}
            </div>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void perform('connect', async () => {
                const result = await api<TelegramStatus>('/telegram/bot', {
                  method: 'POST',
                  body: JSON.stringify({ token: token.trim() }),
                })
                setStatus(result)
                setToken('')
                setChatId('')
                setEnabled(false)
                setChats(null)
                setNotice('Бот проверен. Теперь откройте его в Telegram и нажмите Start.')
              })
            }}
          >
            <label>
              Токен бота
              <input
                type="password"
                maxLength={220}
                autoComplete="new-password"
                spellCheck={false}
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder={
                  status?.configured ? 'Новый токен для замены бота' : 'Вставьте токен из BotFather'
                }
              />
            </label>
            <button className="button" disabled={!!busy || !token.trim()}>
              {busy === 'connect' && <LoaderCircle className="spin" size={14} />}
              {status?.configured ? 'Заменить бота' : 'Проверить и подключить'}
            </button>
          </form>
        </section>
        <section className="telegram-card">
          <div className="telegram-step">
            02 <h2>Выберите чат</h2>
          </div>
          <p>
            Откройте своего бота и нажмите <strong>Start</strong>. Для группы добавьте бота в неё и
            отправьте <code>/start</code>.
          </p>
          <p>Ответа на Start не будет: вернитесь сюда и нажмите «Найти чаты».</p>
          {status?.bot_username && (
            <a
              className="button compact bot-link"
              href={`https://t.me/${encodeURIComponent(status.bot_username)}`}
              target="_blank"
              rel="noreferrer"
            >
              Открыть @{status.bot_username}
              <ExternalLink size={14} />
            </a>
          )}
          <button
            className="button"
            disabled={!!busy || !status?.configured}
            onClick={() =>
              void perform('chats', async () => {
                setChats(await api<Chat[]>('/telegram/chats', { method: 'POST' }))
              })
            }
          >
            {busy === 'chats' && <LoaderCircle className="spin" size={14} />}Найти чаты
          </button>
          {chats?.length === 0 && (
            <p className="chat-hint" role="status">
              Чатов пока нет. Нажмите Start у бота и повторите поиск.
            </p>
          )}
          {!!chats?.length && (
            <label>
              Доступные чаты
              <select value={chatId} onChange={(event) => setChatId(event.target.value)}>
                <option value="">Выберите чат</option>
                {chats.map((chat) => (
                  <option key={chat.id} value={chat.id}>
                    {chat.title} · {chat.id}
                  </option>
                ))}
              </select>
            </label>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void perform('save', async () => {
                const result = await api<TelegramStatus>('/telegram', {
                  method: 'PUT',
                  body: JSON.stringify({ chat_id: chatId.trim(), enabled }),
                })
                setStatus(result)
                setChatId(result.chat_id)
                setEnabled(result.enabled)
                setNotice('Настройки уведомлений сохранены.')
              })
            }}
          >
            <label>
              ID чата
              <input
                type="text"
                value={chatId}
                onChange={(event) => setChatId(event.target.value)}
                placeholder="Выберите чат выше или введите ID"
                spellCheck={false}
              />
            </label>
            <label className="telegram-toggle">
              <input
                type="checkbox"
                checked={enabled}
                disabled={!status?.configured}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              Отправлять события в Telegram
            </label>
            <button
              className="button primary"
              disabled={!!busy || !status || (enabled && !chatId.trim())}
            >
              Сохранить настройки
            </button>
          </form>
        </section>
      </div>
      <section className="telegram-card telegram-delivery">
        <div>
          <div className="telegram-step">
            03 <h2>Проверьте доставку</h2>
          </div>
          <p>Кнопка отправит одно тестовое сообщение в сохранённый чат.</p>
          <button
            className="button"
            disabled={!!busy || !status?.configured || !status.chat_id}
            onClick={() =>
              void perform('test', async () => {
                setStatus(await api<TelegramStatus>('/telegram/test', { method: 'POST' }))
                setNotice('Тестовое сообщение отправлено в сохранённый чат.')
              })
            }
          >
            {busy === 'test' ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}
            Отправить тест
          </button>
          <p className="telegram-test-status">
            {status?.last_test_at
              ? `Последний тест: ${localTime(status.last_test_at)} МСК`
              : 'Доставка ещё не проверялась.'}
          </p>
        </div>
        <div className="telegram-rules">
          <h3>Что придёт в чат</h3>
          <p>
            Сигнал СИЗ или опасной зоны — после подтверждения несколькими кадрами. Ещё одно
            сообщение — при красном уровне через 10 секунд наблюдения.
          </p>
          <p>
            В сообщении будут камера, зона, причина, время и снимок. Повторы одного типа в одной
            зоне — не чаще раза в 30 секунд. История до включения уведомлений не отправляется.
          </p>
        </div>
      </section>
      <section className="telegram-card">
        <div className="telegram-step">
          <h2>Последние отправки</h2>
          {!!status?.pending && (
            <span className="pending-deliveries">В очереди: {status.pending}</span>
          )}
        </div>
        {!status?.deliveries.length ? (
          <p>Подтверждённых событий для отправки пока нет.</p>
        ) : (
          <ul className="telegram-deliveries">
            {status.deliveries.map((delivery) => (
              <li key={delivery.id}>
                <div>
                  <strong>{delivery.zone}</strong>
                  <span>
                    {delivery.severity === 'critical' ? 'Красный сигнал' : 'Подтверждённый сигнал'}
                  </span>
                </div>
                <div>
                  <b className={`delivery-${delivery.status}`}>{deliveryLabels[delivery.status]}</b>
                  {delivery.error && <p>{delivery.error}</p>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
