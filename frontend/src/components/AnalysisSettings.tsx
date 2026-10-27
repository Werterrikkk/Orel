import { CheckCircle2, Cpu, Upload } from 'lucide-react'
import type { Bootstrap, Video } from '../types'

export function AnalysisSettings({
  bootstrap,
  video,
  busy,
  onChoose,
  onUpload,
}: {
  bootstrap: Bootstrap | null
  video: Video | null
  busy: boolean
  onChoose: (video: Video) => Promise<void>
  onUpload: () => void
}) {
  return (
    <div className="model-layout">
      <section className="settings-panel">
        <h2>Источник видео</h2>
        <p className="muted-description">
          Выберите запись для просмотра. Результаты анализа сохраняются вместе с видео.
        </p>
        {bootstrap?.videos.length ? (
          <div className="source-list">
            {bootstrap.videos.map((item) => (
              <button
                key={item.id}
                className={video?.id === item.id ? 'selected' : ''}
                disabled={busy || video?.status === 'processing'}
                onClick={() => void onChoose(item)}
              >
                <img src={item.preview_url} alt="" />
                <span>
                  <strong>{item.name}</strong>
                  <small>
                    {item.width} × {item.height} · {(item.bytes / 1024 / 1024).toFixed(1)} МБ
                  </small>
                </span>
                {video?.id === item.id && <CheckCircle2 size={18} />}
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-source">
            <Upload size={25} />
            <p>Загруженных записей пока нет</p>
            <button className="button" disabled={busy} onClick={() => onUpload()}>
              Выбрать видео
            </button>
          </div>
        )}
      </section>
      <section className="settings-panel">
        <h2>Модель распознавания</h2>
        <p className="muted-description">
          Распознаёт людей, каски и жилеты. Если люди перекрывают друг друга, принадлежность СИЗ
          может определяться неверно.
        </p>
        <div className="model-info">
          <Cpu size={25} />
          <div>
            <strong>YOLO26n</strong>
            <span>
              {bootstrap?.models.ppe.available
                ? 'Дообученные веса СИЗ доступны'
                : 'Веса СИЗ пока не подготовлены'}
            </span>
          </div>
          <span className={`status-label ${bootstrap?.models.ppe.available ? 'good' : ''}`}>
            {bootstrap?.models.ppe.available ? 'Доступна' : 'Ожидание'}
          </span>
        </div>
        <dl className="model-details">
          <div>
            <dt>Обработка записи</dt>
            <dd>Локально, CPU</dd>
          </div>
          <div>
            <dt>Целевая частота</dt>
            <dd>Около 5 кадров/с</dd>
          </div>
          <div>
            <dt>Размер входа</dt>
            <dd>До 640 px</dd>
          </div>
          <div>
            <dt>Проверка на объекте</dt>
            <dd>Не выполнена</dd>
          </div>
        </dl>
        {bootstrap?.models.ppe.metrics && (
          <div className="model-metrics">
            <h3>Оценка на публичной выборке</h3>
            {Object.entries(bootstrap.models.ppe.metrics).map(([name, value]) => (
              <div key={name}>
                <span>{name}</span>
                <strong>{Number(value).toFixed(3)}</strong>
              </div>
            ))}
            <p>Эти значения не подтверждают качество на камерах предприятия.</p>
          </div>
        )}
      </section>
    </div>
  )
}
