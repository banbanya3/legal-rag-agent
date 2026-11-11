<!-- 文件路径: frontend/src/components/StatsView.vue -->
<template>
  <div class="page">
    <div class="page-inner">
      <header class="page-head">
        <div>
          <h1>数据概览</h1>
          <p>对话数据、知识库规模与后端服务状态一览。</p>
        </div>
        <button class="btn btn-ghost" :disabled="loading" @click="refresh">
          <Icon name="refresh" :size="14" :class="{ spin: loading }" />
          刷新
        </button>
      </header>

      <!-- 指标卡 -->
      <div class="metrics">
        <div class="metric">
          <div class="metric-icon violet"><Icon name="message" :size="16" /></div>
          <div class="metric-body">
            <div class="metric-value">{{ stats.sessions ?? '—' }}</div>
            <div class="metric-label">咨询会话</div>
          </div>
        </div>
        <div class="metric">
          <div class="metric-icon blue"><Icon name="layers" :size="16" /></div>
          <div class="metric-body">
            <div class="metric-value">{{ stats.messages ?? '—' }}</div>
            <div class="metric-label">问答消息</div>
          </div>
        </div>
        <div class="metric">
          <div class="metric-icon green"><Icon name="zap" :size="16" /></div>
          <div class="metric-body">
            <div class="metric-value">{{ stats.today_messages ?? '—' }}</div>
            <div class="metric-label">今日消息</div>
          </div>
        </div>
        <div class="metric">
          <div class="metric-icon amber"><Icon name="database" :size="16" /></div>
          <div class="metric-body">
            <div class="metric-value">{{ stats.knowledge?.articles ?? '—' }}</div>
            <div class="metric-label">收录法条</div>
          </div>
        </div>
      </div>

      <div class="two-col">
        <!-- 近 7 天趋势 -->
        <section class="panel">
          <div class="panel-head">
            <h2>近 7 天消息量</h2>
            <span class="panel-sub">日均 {{ average }} 条</span>
          </div>
          <div class="chart">
            <div
              v-for="item in trend"
              :key="item.date"
              class="bar-col"
              :title="`${item.date}: ${item.count} 条`"
            >
              <span class="bar-value" :class="{ zero: !item.count }">{{ item.count }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ height: barHeight(item.count) }" />
              </div>
              <span class="bar-label">{{ item.date }}</span>
            </div>
          </div>
        </section>

        <!-- 服务状态 -->
        <section class="panel">
          <div class="panel-head">
            <h2>服务状态</h2>
            <span class="status-pill" :class="healthClass">
              {{ healthLabel }}
            </span>
          </div>
          <div class="status-list">
            <div class="status-item">
              <span class="status-name">MySQL</span>
              <span class="status-value" :class="state.health?.mysql?.ok ? 'ok' : 'bad'">
                {{ state.health?.mysql?.ok ? '连接正常' : '异常' }}
              </span>
            </div>
            <div class="status-item">
              <span class="status-name">Milvus</span>
              <span class="status-value" :class="state.health?.milvus?.ok ? 'ok' : 'bad'">
                {{ state.health?.milvus?.ok ? `${state.health.milvus.vectors} 条切片` : '异常' }}
              </span>
            </div>
            <div class="status-item">
              <span class="status-name">当前模型</span>
              <span class="status-value mono">{{ state.settings?.model_name || '—' }}</span>
            </div>
            <div class="status-item">
              <span class="status-name">Reranker</span>
              <span class="status-value" :class="state.settings?.use_rerank ? 'ok' : ''">
                {{ state.settings?.use_rerank ? '已启用' : '已关闭' }}
              </span>
            </div>
            <div class="status-item">
              <span class="status-name">存储占用</span>
              <span class="status-value">{{ state.health?.storage_mb ?? '—' }} MB</span>
            </div>
            <div class="status-item">
              <span class="status-name">运行环境</span>
              <span class="status-value mono">
                Python {{ state.health?.python || '—' }} · {{ state.health?.platform || '—' }}
              </span>
            </div>
          </div>
        </section>
      </div>

      <!-- 法律部门分布 -->
      <section class="panel wide">
        <div class="panel-head">
          <h2>法律部门分布</h2>
          <span class="panel-sub">
            {{ stats.knowledge?.docs || 0 }} 份文档 · {{ stats.knowledge?.chunks || 0 }} 条切片 · {{ stats.knowledge?.articles || 0 }} 条法条
          </span>
        </div>

        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>法律部门</th>
                <th class="num">文档</th>
                <th class="num">切片</th>
                <th class="num">法条</th>
                <th class="num">语料字数</th>
                <th>Milvus 集合</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in domains" :key="item.domain">
                <td class="strong">
                  <span class="dot" :style="{ background: item.color || 'var(--primary)' }" />
                  {{ item.label }}
                </td>
                <td class="num">{{ item.docs }}</td>
                <td class="num">{{ item.vectors }}</td>
                <td class="num">{{ item.statutes }}</td>
                <td class="num">{{ (item.chars || 0).toLocaleString('zh-CN') }}</td>
                <td class="muted mono">{{ item.collections || 'law_' + item.domain }}</td>
              </tr>
              <tr v-if="!domains.length">
                <td colspan="6" class="muted center">暂无数据，先在 backend 跑 init_knowledge.py --build</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import Icon from '@/components/Icon.vue'
import { loadHealth, loadStats, state } from '@/stores/app'
import { toastError } from '@/stores/toast'

const loading = ref(false)

const stats = computed(() => state.stats || {})
const domains = computed(() => state.stats?.domains || state.domains || [])
const trend = computed(() => stats.value.trend || [])

const average = computed(() => {
  if (!trend.value.length) return 0
  const total = trend.value.reduce((sum, item) => sum + item.count, 0)
  return (total / trend.value.length).toFixed(1)
})

const maxCount = computed(() =>
  Math.max(1, ...trend.value.map((item) => item.count || 0))
)

function barHeight(count) {
  if (!count) return '2px'
  return `${Math.max(6, (count / maxCount.value) * 100)}%`
}

const healthClass = computed(() => {
  const status = state.health?.status
  if (status === 'ok') return 'ok'
  if (status === 'degraded') return 'warn'
  return 'bad'
})

const healthLabel = computed(() => {
  const status = state.health?.status
  if (status === 'ok') return '全部正常'
  if (status === 'degraded') return '部分异常'
  return '后端离线'
})

async function refresh() {
  loading.value = true
  try {
    await Promise.all([loadStats(), loadHealth()])
  } catch (err) {
    toastError(err.message)
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.page {
  flex: 1;
  overflow-y: auto;
  background: var(--bg);
}
.page-inner {
  max-width: 1000px;
  margin: 0 auto;
  padding: 30px 32px 44px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 22px;
}
.page-head h1 {
  margin: 0 0 5px;
  font-size: 22px;
  font-weight: 650;
  letter-spacing: -0.3px;
}
.page-head p {
  margin: 0;
  color: var(--text-3);
  font-size: 13px;
}
.page-head .btn {
  margin-left: auto;
}

/* ---------- 指标卡 ---------- */
.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.metric {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}
.metric-icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  flex: none;
}
.metric-icon.violet {
  background: #eef0ff;
  color: #4f46e5;
}
.metric-icon.blue {
  background: #e8f4fe;
  color: #0284c7;
}
.metric-icon.green {
  background: var(--success-soft);
  color: var(--success);
}
.metric-icon.amber {
  background: var(--warn-soft);
  color: var(--warn);
}
.metric-value {
  font-size: 21px;
  font-weight: 680;
  letter-spacing: -0.6px;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.metric-label {
  font-size: 11.5px;
  color: var(--text-3);
}

/* ---------- 面板 ---------- */
.two-col {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  gap: 12px;
}
.panel {
  padding: 16px 18px 18px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}
.panel.wide {
  margin-top: 12px;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.panel-head h2 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 650;
}
.panel-sub {
  font-size: 11.5px;
  color: var(--text-3);
  margin-left: auto;
}

/* ---------- 柱状图 ---------- */
.chart {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px;
  height: 150px;
  padding-top: 6px;
}
.bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  gap: 5px;
}
.bar-value {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary-600);
  font-variant-numeric: tabular-nums;
}
.bar-value.zero {
  color: var(--text-3);
  font-weight: 400;
  opacity: 0.6;
}
.bar-track {
  flex: 1;
  width: 100%;
  max-width: 34px;
  display: flex;
  align-items: flex-end;
  background: var(--bg-soft);
  border-radius: 7px;
  overflow: hidden;
}
.bar-fill {
  width: 100%;
  border-radius: 7px;
  background: linear-gradient(180deg, #818cf8, #4f46e5);
  transition: height 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  min-height: 2px;
}
.bar-label {
  font-size: 10.5px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

/* ---------- 状态 ---------- */
.status-pill {
  margin-left: auto;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--bg-soft);
  color: var(--text-3);
}
.status-pill.ok {
  background: var(--success-soft);
  color: var(--success);
}
.status-pill.warn {
  background: var(--warn-soft);
  color: var(--warn);
}
.status-pill.bad {
  background: var(--danger-soft);
  color: var(--danger);
}

.status-list {
  display: flex;
  flex-direction: column;
}
.status-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px dashed var(--border);
  font-size: 12.5px;
}
.status-item:last-child {
  border-bottom: none;
}
.status-name {
  color: var(--text-3);
}
.status-value {
  margin-left: auto;
  color: var(--text-2);
  font-weight: 500;
  text-align: right;
}
.status-value.ok {
  color: var(--success);
}
.status-value.bad {
  color: var(--danger);
}
.status-value.mono {
  font-family: var(--mono);
  font-size: 11.5px;
}

/* ---------- 表格 ---------- */
.table-wrap {
  overflow-x: auto;
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.8px;
}
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}

.data-table th {
  text-align: left;
  font-weight: 600;
  color: var(--text-3);
  font-size: 11.5px;
  padding: 0 10px 8px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.data-table td {
  padding: 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text-2);
}
.data-table tbody tr:last-child td {
  border-bottom: none;
}
.data-table tbody tr:hover {
  background: var(--surface-2);
}
.data-table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.data-table .strong {
  color: var(--text);
  font-weight: 600;
}
.data-table .muted {
  color: var(--text-3);
}
.data-table .center {
  text-align: center;
  padding: 26px;
}

@media (max-width: 900px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .two-col {
    grid-template-columns: 1fr;
  }
  .page-inner {
    padding: 22px 16px;
  }
}
</style>
