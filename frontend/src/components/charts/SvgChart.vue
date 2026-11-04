<template>
  <div class="svg-chart">
    <div v-if="!hasData" class="svg-chart__empty">{{ emptyText }}</div>

    <!-- 环形图 -->
    <div v-else-if="type === 'donut'" class="donut">
      <svg viewBox="0 0 220 220" class="donut__svg" role="img" :aria-label="ariaLabel">
        <circle
          cx="110" cy="110" :r="radius"
          fill="none" stroke="var(--border)" :stroke-width="thickness"
        />
        <circle
          v-for="slice in slices"
          :key="slice.label"
          cx="110" cy="110" :r="radius"
          fill="none"
          :stroke="slice.color"
          :stroke-width="thickness"
          :stroke-dasharray="`${slice.length} ${circumference - slice.length}`"
          :stroke-dashoffset="-slice.offset"
          transform="rotate(-90 110 110)"
        >
          <title>{{ slice.label }}：{{ formatNumber(slice.value) }}{{ suffix }}</title>
        </circle>
        <text x="110" y="106" text-anchor="middle" class="donut__total">
          {{ formatNumber(totalValue) }}
        </text>
        <text x="110" y="126" text-anchor="middle" class="donut__unit">{{ centerLabel }}</text>
      </svg>

      <ul class="legend">
        <li v-for="slice in slices" :key="`legend-${slice.label}`">
          <span class="legend__dot" :style="{ background: slice.color }"></span>
          <span class="legend__label">{{ slice.label }}</span>
          <span class="legend__value">{{ formatNumber(slice.value) }}</span>
          <span class="legend__percent">{{ slice.percent }}%</span>
        </li>
      </ul>
    </div>

    <!-- 折线 / 柱状 / 横向条形 -->
    <svg
      v-else
      :viewBox="`0 0 640 ${chartHeight}`"
      class="chart-svg"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      :aria-label="ariaLabel"
    >
      <g v-for="tick in yTicks" :key="`grid-${tick.value}`">
        <line
          :x1="pad.left" :x2="640 - pad.right"
          :y1="tick.y" :y2="tick.y"
          stroke="var(--border)" stroke-dasharray="3 4"
        />
        <text :x="pad.left - 8" :y="tick.y + 4" text-anchor="end" class="axis-label">
          {{ tick.label }}
        </text>
      </g>

      <template v-if="type === 'hbar'">
        <g v-for="(item, index) in hbars" :key="`hbar-${item.label}`">
          <text :x="0" :y="item.y + 4" class="hbar__label">{{ item.label }}</text>
          <rect
            :x="labelWidth" :y="item.y - item.height / 2"
            :width="item.width" :height="item.height"
            rx="4" :fill="item.color" opacity="0.88"
          >
            <title>{{ item.label }}：{{ formatNumber(item.value) }}{{ suffix }}</title>
          </rect>
          <text :x="labelWidth + item.width + 8" :y="item.y + 4" class="hbar__value">
            {{ formatNumber(item.value) }}{{ suffix }}
          </text>
        </g>
      </template>

      <template v-else>
        <g v-for="(item, index) in categories" :key="`x-${item.label}`">
          <text
            :x="item.x" :y="chartHeight - 10"
            text-anchor="middle" class="axis-label"
          >{{ item.label }}</text>
        </g>

        <!-- 柱状 -->
        <template v-if="type === 'bar'">
          <g v-for="(bar, index) in bars" :key="`bar-${index}`">
            <rect
              :x="bar.x" :y="bar.y" :width="bar.width" :height="bar.height"
              rx="3" :fill="bar.color" opacity="0.88"
            >
              <title>{{ bar.tooltip }}</title>
            </rect>
          </g>
        </template>

        <!-- 折线 -->
        <template v-else>
          <g v-for="line in lines" :key="line.name">
            <path
              :d="line.area" :fill="line.color" opacity="0.07"
            />
            <path
              :d="line.path" fill="none" :stroke="line.color"
              stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"
            />
            <g v-for="(point, index) in line.points" :key="`p-${index}`">
              <circle
                :cx="point.x" :cy="point.y" r="3.2"
                :fill="point.color" stroke="var(--bg-card)" stroke-width="2"
              >
                <title>{{ point.tooltip }}</title>
              </circle>
            </g>
          </g>
        </template>
      </template>
    </svg>

    <ul v-if="type !== 'donut' && showLegend && legendItems.length > 1" class="legend legend--row">
      <li v-for="item in legendItems" :key="`legend-${item.name}`">
        <span class="legend__dot" :style="{ background: item.color }"></span>
        <span class="legend__label">{{ item.name }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** line | bar | hbar | donut */
  type: { type: String, default: 'bar' },
  labels: { type: Array, default: () => [] },
  /** [{ name, values: [], color? }] */
  series: { type: Array, default: () => [] },
  height: { type: Number, default: 220 },
  suffix: { type: String, default: '' },
  showLegend: { type: Boolean, default: true },
  centerLabel: { type: String, default: '合计' },
  emptyText: { type: String, default: '暂无数据' },
})

const PALETTE = [
  'var(--brand-600)',
  'var(--accent-600)',
  'var(--success-600)',
  'var(--info-600)',
  'var(--warning-600)',
  'var(--danger-600)',
  'var(--brand-300)',
]

const pad = { top: 18, right: 18, bottom: 34, left: 44 }
const labelWidth = 120
const radius = 78
const thickness = 22
const circumference = 2 * Math.PI * radius

const points = computed(() => props.series.map((item, index) => ({
  name: item?.name || `序列 ${index + 1}`,
  color: item?.color || PALETTE[index % PALETTE.length],
  values: (item?.values || []).map((value) => {
    const num = Number(value)
    return Number.isFinite(num) ? num : 0
  }),
})))

const hasData = computed(() => (
  props.labels.length > 0
  && points.value.some((item) => item.values.some((value) => value !== 0))
))

const legendItems = computed(() => points.value.map(({ name, color }) => ({ name, color })))

const chartHeight = computed(() => {
  if (props.type === 'hbar') {
    return Math.max(80, props.labels.length * 34 + 24)
  }
  return props.height
})

const ariaLabel = computed(() => {
  const first = points.value[0]
  return first ? `${first.name}图表` : '数据图表'
})

function formatNumber(value) {
  const num = Number(value) || 0
  if (Math.abs(num) >= 10000) {
    return `${(num / 10000).toFixed(1)}万`
  }
  return String(Math.round(num * 10) / 10)
}

function niceMax(value) {
  if (value <= 5) return 5
  const magnitude = 10 ** Math.floor(Math.log10(value))
  const normalized = value / magnitude
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  return step * magnitude
}

const maxValue = computed(() => {
  const all = points.value.flatMap((item) => item.values)
  return niceMax(Math.max(1, ...all))
})

const yTicks = computed(() => {
  const count = 4
  return Array.from({ length: count + 1 }, (_, index) => {
    const ratio = index / count
    return {
      value: maxValue.value * ratio,
      y: pad.top + (chartHeight.value - pad.top - pad.bottom) * (1 - ratio),
      label: formatNumber(maxValue.value * ratio),
    }
  })
})

function yOf(value) {
  const inner = chartHeight.value - pad.top - pad.bottom
  return pad.top + inner * (1 - value / maxValue.value)
}

const categories = computed(() => {
  const length = props.labels.length
  if (!length) return []
  if (props.type === 'line') {
    const inner = 640 - pad.left - pad.right
    return props.labels.map((label, index) => ({
      label,
      x: length === 1 ? pad.left + inner / 2 : pad.left + (inner / Math.max(length - 1, 1)) * index,
    }))
  }
  const slot = (640 - pad.left - pad.right) / length
  return props.labels.map((label, index) => ({
    label,
    x: pad.left + slot * index + slot / 2,
  }))
})

const bars = computed(() => {
  if (props.type !== 'bar') return []
  const count = points.value.length || 1
  const slot = (640 - pad.left - pad.right) / Math.max(props.labels.length, 1)
  const groupWidth = slot * 0.62
  const barWidth = Math.max(4, groupWidth / count)
  const result = []

  points.value.forEach((item, seriesIndex) => {
    item.values.forEach((value, index) => {
      if (index >= props.labels.length) return
      const x = pad.left + slot * index + (slot - groupWidth) / 2 + seriesIndex * barWidth
      const y = yOf(value)
      const baseY = yOf(0)
      result.push({
        x,
        y,
        width: Math.max(2, barWidth - 2),
        height: Math.max(0, baseY - y),
        color: item.color,
        tooltip: `${props.labels[index]} · ${item.name}：${formatNumber(value)}${props.suffix}`,
      })
    })
  })
  return result
})

const lines = computed(() => {
  if (props.type !== 'line') return []
  return points.value.map((item) => {
    const pts = props.labels.map((label, index) => ({
      x: categories.value[index]?.x ?? pad.left,
      y: yOf(item.values[index] || 0),
      color: item.color,
      tooltip: `${label} · ${item.name}：${formatNumber(item.values[index] || 0)}${props.suffix}`,
    }))
    const path = pts.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x},${point.y}`).join(' ')
    const baseY = yOf(0)
    const area = pts.length
      ? `${path} L${pts[pts.length - 1].x},${baseY} L${pts[0].x},${baseY} Z`
      : ''
    return { name: item.name, color: item.color, path, area, points: pts }
  })
})

const hbars = computed(() => {
  if (props.type !== 'hbar') return []
  const item = points.value[0]
  if (!item) return []
  const available = 640 - labelWidth - 70
  const rowHeight = 34
  return props.labels.map((label, index) => {
    const value = item.values[index] || 0
    const width = Math.max(2, (value / maxValue.value) * available)
    return {
      label: label.length > 11 ? `${label.slice(0, 11)}…` : label,
      value,
      width,
      color: PALETTE[index % PALETTE.length],
      height: 16,
      y: 18 + index * rowHeight + rowHeight / 2,
    }
  })
})

const totalValue = computed(() => {
  const item = points.value[0]
  return (item?.values || []).reduce((sum, value) => sum + value, 0)
})

const slices = computed(() => {
  if (props.type !== 'donut') return []
  const item = points.value[0]
  if (!item) return []
  const total = totalValue.value || 1
  let offset = 0
  return props.labels.map((label, index) => {
    const value = item.values[index] || 0
    const ratio = value / total
    const slice = {
      label,
      value,
      color: PALETTE[index % PALETTE.length],
      length: ratio * circumference,
      offset,
      percent: Math.round(ratio * 100),
    }
    offset += ratio * circumference
    return slice
  })
})
</script>

<style scoped>
.svg-chart {
  width: 100%;
}

.svg-chart__empty {
  display: grid;
  place-items: center;
  min-height: 120px;
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

.chart-svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}

.axis-label {
  font-size: 10px;
  fill: var(--text-placeholder);
}

.hbar__label {
  font-size: 11px;
  fill: var(--text-secondary);
}

.hbar__value {
  font-size: 11px;
  fill: var(--text-primary);
  font-weight: 600;
}

.donut {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}

.donut__svg {
  width: 180px;
  flex: 0 0 180px;
  height: auto;
}

.donut__total {
  font-size: 24px;
  font-weight: 600;
  fill: var(--text-primary);
}

.donut__unit {
  font-size: 11px;
  fill: var(--text-placeholder);
}

.legend {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.legend--row {
  flex-direction: row;
  flex-wrap: wrap;
  gap: var(--sp-4);
  margin-top: var(--sp-2);
}

.legend li {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.legend__dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 50%;
}

.legend__label {
  white-space: nowrap;
}

.legend__value {
  color: var(--text-primary);
  font-weight: 600;
}

.legend__percent {
  margin-left: auto;
  color: var(--text-placeholder);
}

.legend--row .legend__label {
  color: var(--text-secondary);
}

@media (max-width: 767px) {
  .donut {
    flex-direction: column;
  }

  .legend {
    width: 100%;
  }
}
</style>
