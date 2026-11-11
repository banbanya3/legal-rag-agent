<!-- 文件路径: frontend/src/components/StatuteView.vue -->
<template>
  <div class="page">
    <div class="page-inner">
      <header class="page-head">
        <div>
          <h1>法条检索</h1>
          <p>
            直接查 MySQL 结构化法条表，不经过大模型 —— 想确认"第几条到底怎么写的"时用这里最快、最准。
            对话里的语义检索会召回相关条文，但只有这张表能保证「一条不多、一条不少」。
          </p>
        </div>
        <div class="head-actions">
          <span class="total-chip">共 {{ state.statuteResult.total }} 条</span>
        </div>
      </header>

      <!-- 检索条件 -->
      <div class="filters">
        <div class="search-box">
          <Icon name="search" :size="16" />
          <input
            v-model="state.statuteQuery"
            type="text"
            placeholder="输入关键词，如：试用期 / 离婚冷静期 / 正当防卫"
            @keyup.enter="loadStatutes(true)"
          />
          <button v-if="state.statuteQuery" class="clear" @click="clearQuery">
            <Icon name="close" :size="13" :stroke-width="2.4" />
          </button>
        </div>

        <select v-model="state.statuteDomain" class="select filter-select" @change="onDomainChange">
          <option value="">全部领域</option>
          <option v-for="item in state.domains" :key="item.domain" :value="item.domain">
            {{ item.label }}
          </option>
        </select>

        <select v-model="state.statuteLaw" class="select filter-select law-select" @change="loadStatutes(true)">
          <option value="">全部法律</option>
          <option v-for="law in filteredLaws" :key="law.law_name" :value="law.law_name">
            {{ law.law_short }}（{{ law.article_count }} 条）
          </option>
        </select>

        <button class="btn btn-primary" @click="loadStatutes(true)">
          <Icon name="search" :size="14" />
          检索
        </button>
      </div>

      <!-- 结果 -->
      <div v-if="state.statuteLoading" class="loading-block">
        <span class="spinner" />
        正在检索…
      </div>

      <div v-else-if="!state.statuteResult.items.length" class="empty-block">
        <Icon name="book" :size="26" />
        <p>没有找到匹配的法条</p>
        <span>换个关键词，或者把领域筛选改成「全部」再试试</span>
      </div>

      <div v-else class="results">
        <article
          v-for="item in state.statuteResult.items"
          :key="item.id"
          class="result-card"
        >
          <div class="result-head">
            <span class="domain-chip" :style="chipStyle(item.domain)">
              {{ item.domain_label }}
            </span>
            <span class="law-name">{{ item.law_short }}</span>
            <span class="article-no">{{ item.article_no }}</span>
            <span v-if="item.heading" class="heading">{{ item.heading }}</span>
            <button class="copy-btn" title="复制条文" @click="copyArticle(item)">
              <Icon :name="copiedId === item.id ? 'check' : 'copy'" :size="13" />
            </button>
          </div>

          <p class="result-text">{{ item.content }}</p>

          <div class="result-foot">
            <span v-if="item.chapter">{{ item.chapter }}</span>
            <span v-if="item.effective_date">施行 {{ item.effective_date }}</span>
            <span class="source">{{ item.source_file }}</span>
          </div>
        </article>

        <!-- 分页 -->
        <div class="pager">
          <button
            class="btn btn-sm btn-ghost"
            :disabled="state.statutePage <= 1"
            @click="changeStatutePage(-1)"
          >
            <Icon name="chevron" :size="13" class="flip" />
            上一页
          </button>
          <span class="pager-info">
            第 {{ state.statutePage }} / {{ totalPages }} 页
          </span>
          <button
            class="btn btn-sm btn-ghost"
            :disabled="state.statutePage >= totalPages"
            @click="changeStatutePage(1)"
          >
            下一页
            <Icon name="chevron" :size="13" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import Icon from '@/components/Icon.vue'
import {
  changeStatutePage,
  loadStatuteLaws,
  loadStatutes,
  state,
} from '@/stores/app'
import { toastSuccess } from '@/stores/toast'

const copiedId = ref('')
const PAGE_SIZE = 15

const totalPages = computed(() =>
  Math.max(1, Math.ceil((state.statuteResult.total || 0) / PAGE_SIZE))
)

/** 领域联动：选了领域就只显示该领域下的法律 */
const filteredLaws = computed(() => {
  const all = state.statuteLaws || []
  if (!state.statuteDomain) return all
  return all.filter((law) => law.domain === state.statuteDomain)
})

const DOMAIN_COLORS = {
  civil: '#2f5fd0',
  labor: '#0f7d5c',
  criminal: '#b3261e',
  business: '#a97b2f',
  digital: '#6d3bbf',
  procedure: '#0e7490',
}

function chipStyle(domain) {
  const color = DOMAIN_COLORS[domain] || 'var(--primary)'
  return { color, background: `${color}18` }
}

function onDomainChange() {
  state.statuteLaw = ''
  loadStatutes(true)
}

function clearQuery() {
  state.statuteQuery = ''
  loadStatutes(true)
}

async function copyArticle(item) {
  const text = `《${item.law_short}》${item.article_no}${item.heading ? `【${item.heading}】` : ''}\n${item.content}`
  try {
    await navigator.clipboard.writeText(text)
    copiedId.value = item.id
    toastSuccess('条文已复制')
    setTimeout(() => (copiedId.value = ''), 1600)
  } catch {
    // 非安全上下文降级
    const el = document.createElement('textarea')
    el.value = text
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
    copiedId.value = item.id
    setTimeout(() => (copiedId.value = ''), 1600)
  }
}

// 输入停顿 380ms 自动搜一次，省得每次都要点按钮
let timer = null
watch(
  () => state.statuteQuery,
  () => {
    clearTimeout(timer)
    timer = setTimeout(() => loadStatutes(true), 380)
  }
)

onMounted(async () => {
  await loadStatuteLaws()
  if (!state.statuteResult.items.length) await loadStatutes(true)
})
</script>

<style scoped>
.page {
  flex: 1;
  overflow-y: auto;
  background: var(--bg);
}
.page-inner {
  max-width: 980px;
  margin: 0 auto;
  padding: 28px 32px 56px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 20px;
}
.page-head h1 {
  margin: 0 0 6px;
  font-size: 21px;
  font-weight: 680;
  letter-spacing: -0.2px;
}
.page-head p {
  margin: 0;
  max-width: 720px;
  font-size: 12.8px;
  line-height: 1.75;
  color: var(--text-2);
}
.head-actions {
  margin-left: auto;
  flex: none;
}
.total-chip {
  font-size: 12px;
  padding: 5px 11px;
  border-radius: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-2);
}

/* ---------- 筛选 ---------- */
.filters {
  display: flex;
  gap: 9px;
  margin-bottom: 20px;
}
.search-box {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  height: 38px;
  padding: 0 12px;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-3);
  transition: border-color 0.16s, box-shadow 0.16s;
}
.search-box:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-ring);
}
.search-box input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: none;
  font-size: 13.2px;
  color: var(--text);
}
.search-box input::placeholder {
  color: var(--text-3);
}
.clear {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--bg-soft);
  color: var(--text-3);
}
.filter-select {
  width: 150px;
  height: 38px;
  flex: none;
}
.law-select {
  width: 210px;
}

/* ---------- 结果 ---------- */
.results {
  display: flex;
  flex-direction: column;
  gap: 11px;
}
.result-card {
  padding: 14px 17px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  border-left: 3px solid var(--gold);
  transition: box-shadow 0.16s;
}
.result-card:hover {
  box-shadow: var(--shadow);
}
.result-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.domain-chip {
  font-size: 10.5px;
  font-weight: 600;
  padding: 1.5px 7px;
  border-radius: 5px;
  flex: none;
}
.law-name {
  font-size: 13.2px;
  font-weight: 650;
  color: var(--text);
}
.article-no {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--primary-600);
  font-variant-numeric: tabular-nums;
}
.heading {
  font-size: 12.3px;
  color: var(--text-2);
}
.copy-btn {
  margin-left: auto;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  color: var(--text-3);
}
.copy-btn:hover {
  background: var(--bg-soft);
  color: var(--text-2);
}
.result-text {
  margin: 9px 0 10px;
  font-family: var(--serif);
  font-size: 14px;
  line-height: 1.85;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
.result-foot {
  display: flex;
  gap: 14px;
  font-size: 11.2px;
  color: var(--text-3);
  padding-top: 8px;
  border-top: 1px dashed var(--border);
}
.source {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 10.5px;
  opacity: 0.75;
}

/* ---------- 分页 ---------- */
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 18px 0 4px;
}
.pager-info {
  font-size: 12.2px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.flip {
  transform: rotate(90deg);
}
.pager .btn:last-child Icon {
  transform: rotate(-90deg);
}

.loading-block,
.empty-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 60px 20px;
  color: var(--text-3);
  font-size: 12.8px;
}
.empty-block p {
  margin: 4px 0 0;
  color: var(--text-2);
  font-size: 13.5px;
}
</style>
