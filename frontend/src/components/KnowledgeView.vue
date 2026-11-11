<!-- 文件路径: frontend/src/components/KnowledgeView.vue -->
<template>
  <div class="page">
    <div class="page-inner">
      <header class="page-head">
        <div>
          <h1>知识库</h1>
          <p>
            内置 {{ totalDocs }} 份现行法律与司法解释，按六大法律部门分域索引。
            每份文档会同时写入两处：Milvus 向量库（语义检索）与 MySQL 法条表（精确查询）。
            在下方上传的资料会进入独立的「我的文档」集合，不会和内置法律库混在一起。
          </p>
        </div>
        <div class="head-actions">
          <button
            class="btn btn-ghost"
            :disabled="state.knowledgeLoading"
            @click="rebuildAll"
          >
            <Icon name="refresh" :size="14" :class="{ spin: state.knowledgeLoading }" />
            {{ state.knowledgeLoading ? '正在重建…' : '重建全部索引' }}
          </button>
        </div>
      </header>

      <!-- 概况条 -->
      <div class="summary">
        <div class="summary-item">
          <span class="summary-num">{{ totalDocs }}</span>
          <span class="summary-label">法律文档</span>
        </div>
        <div class="summary-divider" />
        <div class="summary-item">
          <span class="summary-num">{{ totalChunks }}</span>
          <span class="summary-label">向量切片</span>
        </div>
        <div class="summary-divider" />
        <div class="summary-item">
          <span class="summary-num">{{ totalArticles }}</span>
          <span class="summary-label">结构化法条</span>
        </div>
        <div class="summary-divider" />
        <div class="summary-item">
          <span class="summary-num">{{ totalChars.toLocaleString() }}</span>
          <span class="summary-label">语料字数</span>
        </div>
      </div>

      <!-- 上传区 -->
      <div
        class="dropzone"
        :class="{ dragging, uploading: state.uploading }"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
        @click="fileInput?.click()"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".txt,.md,.markdown,.pdf,.docx"
          hidden
          @change="onPick"
        />
        <div class="dz-icon">
          <Icon
            :name="state.uploading ? 'refresh' : 'upload'"
            :size="20"
            :class="{ spin: state.uploading }"
          />
        </div>
        <div class="dz-text">
          <strong>{{ state.uploading ? '正在向量化…' : '上传我的法律资料' }}</strong>
          <span>
            支持 .txt / .md / .pdf / .docx，单个文件不超过 {{ maxMb }}MB。
            Markdown 用「### 第X条」标注可自动进法条表；PDF / Word 提取后只做语义检索
          </span>
        </div>
        <div v-if="state.uploading" class="dz-progress">
          <span :style="{ width: `${state.uploadProgress}%` }" />
        </div>
      </div>

      <!-- 领域卡片 -->
      <section class="block">
        <div class="block-head">
          <h2>法律部门</h2>
          <span class="block-sub">6 个领域 · 独立集合，可单独重建</span>
        </div>

        <div class="cards">
          <article v-for="item in state.domains" :key="item.domain" class="card">
            <div class="card-top">
              <div class="card-icon" :style="{ color: item.color, background: tint(item.color) }">
                <Icon :name="domainIcon(item.domain)" :size="16" />
              </div>
              <div class="card-title">
                <h3>{{ item.label }}</h3>
                <code>{{ item.collections || 'law_' + item.domain }}</code>
              </div>
              <span class="chunk-badge">{{ item.vectors }} 切片</span>
            </div>

            <p class="card-desc">{{ item.desc }}</p>

            <div class="card-meta">
              <span>
                <Icon name="file" :size="12" />
                {{ item.docs }} 份文档
              </span>
              <span>
                <Icon name="book" :size="12" />
                {{ item.statutes }} 条法条
              </span>
              <span>{{ (item.chars / 1000).toFixed(1) }}k 字</span>
            </div>

            <div class="card-docs">
              <span v-for="doc in item.files" :key="doc.filename" class="doc-tag">
                {{ doc.filename.replace(/\.md$/, '') }}
              </span>
              <span v-if="!item.files?.length" class="doc-tag empty">暂无文档</span>
            </div>

            <button
              class="btn btn-sm card-btn"
              :disabled="state.knowledgeLoading"
              @click="rebuildOne(item)"
            >
              <Icon name="refresh" :size="12" />
              重建此领域
            </button>
          </article>
        </div>
      </section>

      <!-- 已上传文档 -->
      <section class="block">
        <div class="block-head">
          <h2>我上传的文档</h2>
          <span class="block-sub">{{ state.documents.length }} 个文件</span>
        </div>

        <div v-if="!state.documents.length" class="empty-docs">
          <Icon name="upload" :size="22" />
          <p>还没有上传过文档</p>
          <span>传一份 txt 或 md，问答时会一起参与检索</span>
        </div>

        <div v-else class="doc-table">
          <div v-for="doc in state.documents" :key="doc.filename" class="doc-row">
            <div class="doc-icon"><Icon name="file" :size="15" /></div>
            <div class="doc-main">
              <div class="doc-name">{{ doc.filename }}</div>
              <div class="doc-meta">{{ doc.size_kb }} KB · {{ doc.modified_at }}</div>
            </div>
            <button class="btn btn-sm btn-danger" @click="onDelete(doc)">
              <Icon name="trash" :size="12" />
              删除
            </button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import Icon from '@/components/Icon.vue'
import {
  loadKnowledge,
  rebuildKnowledge,
  removeDocument,
  state,
  uploadDocument,
} from '@/stores/app'
import { askConfirm } from '@/stores/confirm'
import { toastError } from '@/stores/toast'

const fileInput = ref(null)
const dragging = ref(false)
const maxMb = 10

const totalDocs = computed(() =>
  state.domains.reduce((sum, item) => sum + (item.docs || 0), 0)
)
const totalChunks = computed(() =>
  state.domains.reduce((sum, item) => sum + (item.vectors || 0), 0)
)
const totalArticles = computed(() =>
  state.domains.reduce((sum, item) => sum + (item.statutes || 0), 0)
)
const totalChars = computed(() =>
  state.domains.reduce((sum, item) => sum + (item.chars || 0), 0)
)

/** 领域图标映射。放在前端而不是后端，是因为这属于展示逻辑。 */
const DOMAIN_ICONS = {
  civil: 'heart',
  labor: 'briefcase',
  criminal: 'alert',
  business: 'chart',
  digital: 'shield',
  procedure: 'gavel',
}

function domainIcon(key) {
  return DOMAIN_ICONS[key] || 'folder'
}

/** 把主题色转成 12% 透明度的浅底，避免为每个领域硬编码一个背景色 */
function tint(color) {
  if (!color) return 'var(--bg-soft)'
  return `${color}1f`
}

function validate(file) {
  const ok = /\.(txt|md|markdown|pdf|docx)$/i.test(file.name)
  if (!ok) {
    toastError('只支持 .txt / .md / .markdown / .pdf / .docx 格式')
    return false
  }
  if (file.size > maxMb * 1024 * 1024) {
    toastError(`文件不能超过 ${maxMb}MB`)
    return false
  }
  return true
}

async function handleFile(file) {
  if (!file || !validate(file)) return
  await uploadDocument(file)
}

function onPick(event) {
  const file = event.target.files?.[0]
  handleFile(file)
  event.target.value = ''
}

function onDrop(event) {
  dragging.value = false
  handleFile(event.dataTransfer?.files?.[0])
}

async function rebuildOne(item) {
  const ok = await askConfirm({
    title: `重建「${item.label}」？`,
    message: '会删除该领域现有向量，重新切分并调用 Embedding 接口。',
    detail: '文件较多时可能耗时一两分钟，期间该领域暂时检索不到内容。',
    confirmText: '开始重建',
    danger: false,
  })
  if (ok) await rebuildKnowledge({ domain: item.domain, force: true })
}

async function rebuildAll() {
  const ok = await askConfirm({
    title: '重建全部索引？',
    message: '6 个领域、全部法律文档都会重新向量化。',
    detail: '这会重新消耗 Embedding 额度，通常需要几分钟。文件没改动的部分走增量逻辑，不会重复计费。',
    confirmText: '全部重建',
    danger: false,
  })
  if (ok) await rebuildKnowledge({ force: false })
}

async function onDelete(doc) {
  const ok = await askConfirm({
    title: '删除这个文档？',
    message: `「${doc.filename}」会从磁盘和向量库中一起移除。`,
    detail: '内置法律库的文件不在此列表中，不会被误删。',
    confirmText: '删除文档',
  })
  if (ok) await removeDocument(doc.filename)
}

onMounted(() => {
  if (!state.domains.length) loadKnowledge()
})
</script>

<style scoped>
.page {
  flex: 1;
  overflow-y: auto;
  background: var(--bg);
}
.page-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 28px 32px 56px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 22px;
}
.page-head h1 {
  margin: 0 0 6px;
  font-size: 21px;
  font-weight: 680;
  letter-spacing: -0.2px;
}
.page-head p {
  margin: 0;
  max-width: 760px;
  font-size: 12.8px;
  line-height: 1.75;
  color: var(--text-2);
}
.head-actions {
  margin-left: auto;
  flex: none;
}

/* ---------- 概况 ---------- */
.summary {
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 16px 22px;
  margin-bottom: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}
.summary-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.summary-num {
  font-size: 19px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
  color: var(--primary);
  letter-spacing: -0.4px;
}
.summary-label {
  font-size: 11.5px;
  color: var(--text-3);
}
.summary-divider {
  width: 1px;
  height: 26px;
  background: var(--border);
}

/* ---------- 上传 ---------- */
.dropzone {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  margin-bottom: 26px;
  border: 1.5px dashed var(--border-strong);
  border-radius: var(--radius);
  background: var(--surface-2);
  cursor: pointer;
  transition: border-color 0.16s, background 0.16s;
  overflow: hidden;
}
.dropzone:hover,
.dropzone.dragging {
  border-color: var(--primary);
  background: var(--primary-soft);
}
.dropzone.uploading {
  pointer-events: none;
}
.dz-icon {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--primary);
  flex: none;
}
.dz-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.dz-text strong {
  font-size: 13.5px;
  font-weight: 600;
}
.dz-text span {
  font-size: 12px;
  color: var(--text-3);
}
.dz-progress {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 3px;
  width: 100%;
  background: var(--border);
}
.dz-progress span {
  display: block;
  height: 100%;
  background: var(--primary);
  transition: width 0.2s;
}

/* ---------- 卡片 ---------- */
.block {
  margin-bottom: 32px;
}
.block-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
}
.block-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
}
.block-sub {
  font-size: 12px;
  color: var(--text-3);
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 14px;
}
.card {
  display: flex;
  flex-direction: column;
  padding: 16px 17px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.18s, border-color 0.18s;
}
.card:hover {
  box-shadow: var(--shadow);
  border-color: var(--border-strong);
}
.card-top {
  display: flex;
  align-items: center;
  gap: 10px;
}
.card-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex: none;
}
.card-title {
  min-width: 0;
  flex: 1;
}
.card-title h3 {
  margin: 0;
  font-size: 13.8px;
  font-weight: 650;
}
.card-title code {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-3);
}
.chunk-badge {
  font-size: 10.8px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--primary-soft);
  color: var(--primary-600);
  flex: none;
}
.card-desc {
  margin: 10px 0 12px;
  font-size: 12.2px;
  line-height: 1.7;
  color: var(--text-2);
  min-height: 42px;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 11.5px;
  color: var(--text-3);
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--border);
}
.card-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.card-docs {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin: 10px 0 12px;
}
.doc-tag {
  font-size: 10.8px;
  padding: 2px 7px;
  border-radius: 5px;
  background: var(--bg-soft);
  color: var(--text-2);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-tag.empty {
  color: var(--text-3);
  background: transparent;
  border: 1px dashed var(--border-strong);
}
.card-btn {
  margin-top: auto;
  align-self: flex-start;
}

/* ---------- 上传列表 ---------- */
.empty-docs {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 34px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius);
  color: var(--text-3);
  font-size: 12.5px;
}
.empty-docs p {
  margin: 4px 0 0;
  color: var(--text-2);
  font-size: 13px;
}
.doc-table {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--surface);
}
.doc-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 15px;
  border-bottom: 1px solid var(--border);
}
.doc-row:last-child {
  border-bottom: none;
}
.doc-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--bg-soft);
  color: var(--text-2);
  flex: none;
}
.doc-main {
  flex: 1;
  min-width: 0;
}
.doc-name {
  font-size: 13px;
  font-weight: 550;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-meta {
  font-size: 11.3px;
  color: var(--text-3);
  margin-top: 1px;
}
</style>
