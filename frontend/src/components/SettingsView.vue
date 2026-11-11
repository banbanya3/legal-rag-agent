<!-- 文件路径: frontend/src/components/SettingsView.vue -->
<template>
  <div class="page">
    <div class="page-inner">
      <header class="page-head">
        <div>
          <h1>系统设置</h1>
          <p>修改后立即生效，配置写入 MySQL 的 system_setting 表。模型 Key 只在本机使用，接口永远返回脱敏值。</p>
        </div>
      </header>

      <div class="page-body">
          <div v-if="state.settingsLoading && !state.settings" class="loading">
            <span class="spinner" /> 正在读取当前配置…
          </div>

          <template v-else>
            <!-- ============ 模型服务 ============ -->
            <section class="section">
              <div class="section-title">
                <Icon name="cpu" :size="15" />
                <span>模型服务</span>
              </div>

              <div class="provider-chips">
                <button
                  v-for="preset in state.models"
                  :key="preset.provider"
                  class="provider-chip"
                  :class="{ active: form.provider === preset.provider }"
                  @click="pickProvider(preset)"
                >
                  {{ preset.provider_label }}
                </button>
              </div>

              <div class="field">
                <label class="field-label">
                  模型名称
                  <span class="badge" v-if="state.settings">
                    当前：{{ state.settings.model_name }}
                  </span>
                </label>
                <ModelCombobox
                  v-model="form.model_name"
                  :options="modelOptions"
                  placeholder="如 glm-4-flash / deepseek-chat"
                />
                <span class="field-hint">
                  推理型模型（如 glm-5.3-flash）回答质量更好，但 Agent 多轮调用会慢一些。
                </span>
              </div>

              <div class="field">
                <label class="field-label">Base URL</label>
                <input
                  v-model="form.base_url"
                  class="input"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="https://open.bigmodel.cn/api/paas/v4/"
                />
              </div>

              <div class="field">
                <label class="field-label">
                  API Key
                  <span class="badge" v-if="state.settings?.has_api_key">
                    已保存 {{ state.settings.api_key_masked }}
                  </span>
                </label>
                <div class="input-with-action">
                  <input
                    v-model="form.api_key"
                    class="input"
                    :type="showKey ? 'text' : 'password'"
                    :placeholder="
                      state.settings?.has_api_key
                        ? '留空表示沿用已保存的 Key'
                        : '请输入 API Key'
                    "
                    autocomplete="new-password"
                  />
                  <button class="input-action" @click="showKey = !showKey">
                    <Icon :name="showKey ? 'eyeOff' : 'eye'" :size="16" />
                  </button>
                </div>
                <span class="field-hint">
                  前端不回显明文密钥；留空保存不会覆盖数据库中已有的 Key。
                </span>
              </div>

              <div class="field">
                <label class="field-label">
                  温度 temperature
                  <span class="value-tag">{{ form.temperature.toFixed(2) }}</span>
                </label>
                <input
                  v-model.number="form.temperature"
                  type="range"
                  min="0"
                  max="1.5"
                  step="0.05"
                  class="slider"
                  :style="{ '--fill': pct(form.temperature, 0, 1.5) }"
                />
                <span class="field-hint">
                  越低越严谨（适合知识库问答），越高越发散（适合创意写作）。
                </span>
              </div>
            </section>

            <!-- ============ 检索策略 ============ -->
            <section class="section">
              <div class="section-title">
                <Icon name="layers" :size="15" />
                <span>检索策略</span>
              </div>

              <div class="field">
                <label class="field-label">
                  向量召回条数 top_k
                  <span class="value-tag">{{ form.top_k }}</span>
                </label>
                <input
                  v-model.number="form.top_k"
                  type="range"
                  min="1"
                  max="30"
                  step="1"
                  class="slider"
                  :style="{ '--fill': pct(form.top_k, 1, 30) }"
                />
                <span class="field-hint">第一阶段从 Milvus 捞多少条候选切片。</span>
              </div>

              <div class="field">
                <label class="field-label">
                  精排保留条数 rerank_n
                  <span class="value-tag">{{ form.rerank_n }}</span>
                </label>
                <input
                  v-model.number="form.rerank_n"
                  type="range"
                  min="1"
                  max="10"
                  step="1"
                  class="slider"
                  :style="{ '--fill': pct(form.rerank_n, 1, 10) }"
                />
                <span class="field-hint">智谱 Reranker 精排后，最终喂给模型的切片数量。</span>
              </div>

              <label class="switch-row">
                <div>
                  <div class="switch-row-title">启用二阶段精排</div>
                  <div class="switch-row-desc">
                    关闭后只走向量检索，速度更快，但引用准确度会下降。
                  </div>
                </div>
                <span class="switch">
                  <input type="checkbox" v-model="form.use_rerank" />
                  <span class="switch-track" />
                </span>
              </label>
            </section>

            <!-- ============ 连通性测试 ============ -->
            <section class="section">
              <div class="section-title">
                <Icon name="zap" :size="15" />
                <span>连通性测试</span>
              </div>
              <p class="section-desc">
                会真实发一条最小请求，验证 Base URL、API Key、模型名三者是否匹配。
              </p>
              <button class="btn btn-ghost test-btn" :disabled="testing" @click="runTest">
                <span v-if="testing" class="spinner" />
                <Icon v-else name="refresh" :size="14" />
                {{ testing ? '正在测试…' : '测试连接' }}
              </button>

              <div v-if="testResult" class="test-result" :class="testResult.success ? 'ok' : 'fail'">
                <div class="test-head">
                  <Icon :name="testResult.success ? 'check' : 'alert'" :size="15" />
                  <strong>{{ testResult.success ? '连接成功' : '连接失败' }}</strong>
                  <span v-if="testResult.latency_ms" class="latency">
                    {{ testResult.latency_ms }}ms
                  </span>
                </div>
                <p>{{ testResult.message }}</p>
                <pre v-if="testResult.model_reply" class="reply">{{ testResult.model_reply }}</pre>
              </div>
            </section>
          </template>
        </div>

        <footer class="page-foot">
          <button class="btn" @click="reset">重置</button>
          <button class="btn btn-primary" :disabled="saving || !valid" @click="save">
            <span v-if="saving" class="spinner light" />
            {{ saving ? '保存中…' : '保存并生效' }}
          </button>
        </footer>
      </div>
    </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

import Icon from '@/components/Icon.vue'
import ModelCombobox from '@/components/ModelCombobox.vue'
import {
  saveSettings,
  state,
  testConnection,
} from '@/stores/app'
import { toastError } from '@/stores/toast'

const showKey = ref(false)
const testing = ref(false)
const saving = ref(false)
const testResult = ref(null)

const form = reactive({
  provider: 'zhipu',
  model_name: '',
  api_key: '',
  base_url: '',
  temperature: 0.1,
  top_k: 10,
  rerank_n: 3,
  use_rerank: true,
})

const modelOptions = computed(() => {
  const preset = state.models.find((item) => item.provider === form.provider)
  return preset?.models || []
})

const valid = computed(
  () =>
    form.model_name.trim().length > 0 &&
    /^https?:\/\//.test(form.base_url.trim())
)

/**
 * 把数据库里的当前配置回填到表单。
 *
 * 这里踩过一个坑：原来只写了 watch，没加 immediate，也没在 onMounted 里调。
 * 结果是 —— 设置页是 v-if 渲染的，每次切走就销毁、切回来重建，form 重置成空。
 * 而这个时候 state.settings 早就有值了，引用没变，watch 根本不触发，
 * 于是输入框全空：模型名要重新选，Base URL 显示的是 placeholder 不是真值，
 * 保存按钮因为校验不通过一直是灰的。
 *
 * 解法：填充分成两个时机 —— 挂载时主动填一次，settings 变化时再填。
 */
function fillForm() {
  if (!state.settings) return
  Object.assign(form, {
    provider: state.settings.provider,
    model_name: state.settings.model_name,
    api_key: '',                       // 密钥不回显，留空表示沿用已保存的
    base_url: state.settings.base_url,
    temperature: state.settings.temperature,
    top_k: state.settings.top_k,
    rerank_n: state.settings.rerank_n,
    use_rerank: state.settings.use_rerank,
  })
  testResult.value = null
}

// 时机一：组件挂载（每次切进设置页都会触发）
onMounted(fillForm)

// 时机二：settings 真的变了（比如刚拉完接口，或保存成功后后端返回新值）
watch(() => state.settings, fillForm, { deep: true })

function pickProvider(preset) {
  form.provider = preset.provider
  if (preset.base_url) form.base_url = preset.base_url
  if (preset.models?.length) form.model_name = preset.models[0].name
  testResult.value = null
}

/** 把 0~1 的比例算出来喂给滑块轨道的渐变，让已填充部分显示主题色 */
function pct(value, min, max) {
  const ratio = (Number(value) - min) / (max - min)
  return `${Math.max(0, Math.min(1, ratio)) * 100}%`
}

async function runTest() {
  if (!valid.value) {
    toastError('请先填写合法的模型名称与 Base URL')
    return
  }
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testConnection({
      model_name: form.model_name.trim(),
      api_key: form.api_key.trim() || null,
      base_url: form.base_url.trim(),
      temperature: form.temperature,
    })
  } catch (err) {
    testResult.value = { success: false, message: err.message }
  } finally {
    testing.value = false
  }
}

function reset() {
  // 把表单还原成"当前已保存的配置"，用于改乱了之后一键回到原状
  fillForm()
}

async function save() {
  if (!valid.value) {
    toastError('请检查模型名称与 Base URL')
    return
  }
  saving.value = true
  try {
    await saveSettings({
      provider: form.provider,
      model_name: form.model_name.trim(),
      api_key: form.api_key.trim() || null,
      base_url: form.base_url.trim(),
      temperature: form.temperature,
      top_k: form.top_k,
      rerank_n: form.rerank_n,
      use_rerank: form.use_rerank,
    })
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
/* 页面级布局，和法条检索 / 知识库 / 数据概览保持一致 */
.page {
  height: 100%;
  overflow-y: auto;
  padding: 26px 30px 40px;
}

.page-inner {
  max-width: 760px;
  margin: 0 auto;
}

.page-head {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border);
}
.page-head h1 {
  margin: 0;
  font-family: var(--serif);
  font-size: 21px;
  font-weight: 600;
  letter-spacing: 0.3px;
}
.page-head p {
  margin: 6px 0 0;
  max-width: 620px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-3);
}

.page-body {
  padding: 4px 0 0;
}

.page-foot {
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  padding: 16px 0 0;
  margin-top: 18px;
  border-top: 1px solid var(--border);
}
.page-foot .btn {
  min-width: 96px;
}

.section {
  padding: 18px 0;
  border-bottom: 1px dashed var(--border);
}
.section:last-child {
  border-bottom: none;
}
.section-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13.5px;
  font-weight: 650;
  color: var(--text);
  margin-bottom: 14px;
}
.section-title svg {
  color: var(--primary);
}
.section-desc {
  margin: -6px 0 12px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
}

.provider-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 16px;
}
.provider-chip {
  height: 28px;
  padding: 0 11px;
  border-radius: 8px;
  border: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-2);
  transition: all 0.15s;
}
.provider-chip:hover {
  border-color: var(--border-strong);
  background: var(--surface-2);
}
.provider-chip.active {
  background: var(--primary-soft);
  border-color: #c9cdf6;
  color: var(--primary-600);
  font-weight: 600;
}

.badge {
  font-size: 10.5px;
  font-weight: 500;
  color: var(--text-3);
  background: var(--bg-soft);
  padding: 1px 6px;
  border-radius: 5px;
  font-family: var(--mono);
}
.value-tag {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--primary-600);
  background: var(--primary-soft);
  padding: 1px 7px;
  border-radius: 5px;
  font-variant-numeric: tabular-nums;
}

.input-with-action {
  position: relative;
}
.input-with-action .input {
  padding-right: 40px;
}
.input-action {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--text-3);
}
.input-action:hover {
  background: var(--bg-soft);
  color: var(--text-2);
}

.slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 4px;
  border-radius: 999px;
  background: linear-gradient(
    to right,
    var(--primary) 0%,
    var(--primary) var(--fill, 50%),
    #e3e5ee var(--fill, 50%),
    #e3e5ee 100%
  );
  outline: none;
  margin: 8px 0 4px;
}
.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 15px;
  height: 15px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid var(--primary);
  box-shadow: 0 1px 4px rgba(17, 24, 39, 0.2);
  cursor: pointer;
}
.slider::-moz-range-thumb {
  width: 15px;
  height: 15px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid var(--primary);
  cursor: pointer;
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 11px 13px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  cursor: pointer;
}
.switch-row-title {
  font-size: 13px;
  font-weight: 550;
}
.switch-row-desc {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 1px;
  line-height: 1.5;
}
.switch-row .switch {
  margin-left: auto;
  flex: none;
}

.test-btn {
  width: 100%;
}
.test-result {
  margin-top: 12px;
  padding: 11px 13px;
  border-radius: 10px;
  font-size: 12.2px;
  border: 1px solid;
}
.test-result.ok {
  background: var(--success-soft);
  border-color: #bfe9db;
  color: #0b6b52;
}
.test-result.fail {
  background: var(--danger-soft);
  border-color: #f6cbcc;
  color: #a12a2e;
}
.test-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
}
.latency {
  margin-left: auto;
  font-size: 11px;
  opacity: 0.75;
  font-variant-numeric: tabular-nums;
}
.test-result p {
  margin: 0;
  line-height: 1.6;
  word-break: break-all;
}
.reply {
  margin: 7px 0 0;
  padding: 7px 9px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.65);
  font-family: var(--mono);
  font-size: 11.4px;
  white-space: pre-wrap;
  max-height: 90px;
  overflow-y: auto;
}

.loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  padding: 60px 0;
  color: var(--text-3);
  font-size: 13px;
}
.spinner {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  border: 2px solid var(--border-strong);
  border-top-color: var(--primary);
  animation: spin 0.8s linear infinite;
  display: inline-block;
}
.spinner.light {
  border-color: rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
}
</style>
