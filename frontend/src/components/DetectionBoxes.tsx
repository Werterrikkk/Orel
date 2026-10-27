import type { Detection } from '../types'

const names = { person: 'Человек', helmet: 'Каска', vest: 'Жилет' }
const colors = { person: '#a7e3ac', helmet: '#ffd877', vest: '#8ddbe9' }

export function DetectionBoxes({
  objects,
  width = 1000,
  height = 1000,
}: {
  objects: Detection[]
  width?: number
  height?: number
}) {
  return (
    <>
      {objects.map((item, index) => {
        const [x1, y1, x2, y2] = item.box
        const label =
          names[item.kind] + (item.kind === 'person' && item.track_id ? ` · ${item.track_id}` : '')
        const labelWidth = label.length * 7 + 16
        const top = Math.max(3, y1 * height - 22)
        return (
          <g key={index} className={`detection ${item.kind}`}>
            <rect
              x={x1 * width}
              y={y1 * height}
              width={(x2 - x1) * width}
              height={(y2 - y1) * height}
              style={{ stroke: colors[item.kind], fill: 'none' }}
            />
            <g
              transform={`translate(${Math.max(0, Math.min(x1 * width, width - labelWidth))},${top})`}
            >
              <rect
                width={labelWidth}
                height="20"
                rx="3"
                style={{ fill: colors[item.kind], stroke: 'none' }}
              />
              <text x="8" y="14" style={{ fill: '#102019', fontSize: 12, fontWeight: 650 }}>
                {label}
              </text>
            </g>
          </g>
        )
      })}
    </>
  )
}
