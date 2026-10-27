import { Camera, CircleHelp, ClipboardList, Monitor, Send } from 'lucide-react'
export type ConsolePage = 'camera' | 'events' | 'settings' | 'notifications'

export function Sidebar({
  page,
  pending,
  onPage,
  onHelp,
}: {
  page: ConsolePage
  pending: number
  onPage: (page: ConsolePage) => void
  onHelp: () => void
}) {
  return (
    <aside className="console-nav">
      <button
        className="console-brand"
        title="orel — видеонаблюдение"
        aria-label="orel — видеонаблюдение"
        onClick={() => onPage('camera')}
      >
        <img className="orel-mark" src="/orel-logo.jpg" alt="" aria-hidden="true" />
        <span>OREL</span>
      </button>
      <nav aria-label="Основная навигация">
        {[
          { id: 'camera' as const, label: 'Видеонаблюдение', icon: Monitor },
          { id: 'events' as const, label: 'Журнал событий', icon: ClipboardList },
          { id: 'settings' as const, label: 'Камеры', icon: Camera },
          { id: 'notifications' as const, label: 'Уведомления', icon: Send },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            title={label}
            aria-label={label}
            aria-current={page === id ? 'page' : undefined}
            className={page === id ? 'active' : ''}
            onClick={() => onPage(id)}
          >
            <Icon size={22} strokeWidth={1.6} />
            <span>
              {id === 'camera'
                ? 'Эфир'
                : id === 'events'
                  ? 'Журнал'
                  : id === 'settings'
                    ? 'Камеры'
                    : 'Telegram'}
            </span>
            {id === 'events' && pending > 0 && <b>{Math.min(99, pending)}</b>}
          </button>
        ))}
      </nav>
      <button className="console-nav-help" title="Справка" aria-label="Справка" onClick={onHelp}>
        <CircleHelp size={21} strokeWidth={1.5} />
      </button>
      <span className="console-nav-version">OREL</span>
    </aside>
  )
}
