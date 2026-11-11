<!-- 文件路径: frontend/src/components/Icon.vue -->
<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="inner"
  />
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 18 },
  strokeWidth: { type: [Number, String], default: 1.8 },
})

// 手写的一套线性图标（风格对齐 lucide），避免为了几个图标再装一个依赖包
const PATHS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  search:
    '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  message:
    '<path d="M21 14a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  trash:
    '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M10 11v6M14 11v6"/>',
  pencil:
    '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  settings:
    '<path d="M4 21v-6M4 11V3M12 21v-8M12 9V3M20 21v-4M20 13V3"/><path d="M2 15h4M10 9h4M18 17h4"/>',
  database:
    '<ellipse cx="12" cy="5" rx="8.5" ry="3"/><path d="M3.5 5v7c0 1.66 3.8 3 8.5 3s8.5-1.34 8.5-3V5"/><path d="M3.5 12v7c0 1.66 3.8 3 8.5 3s8.5-1.34 8.5-3v-7"/>',
  chart:
    '<path d="M4 20h16"/><path d="M7 20v-6M12 20V7M17 20v-9"/>',
  send: '<path d="M21 3 10.5 13.5"/><path d="M21 3l-6.5 18-4-8-8-4z"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/>',
  copy:
    '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  upload:
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 9l5-5 5 5M12 4v12"/>',
  refresh:
    '<path d="M21 4v6h-6"/><path d="M3 20v-6h6"/><path d="M3.5 9a8.5 8.5 0 0 1 14.3-3L21 10M21 14a8.5 8.5 0 0 1-14.3 3L3 14"/>',
  chevron: '<path d="M6 9l6 6 6-6"/>',
  chevronRight: '<path d="M9 6l6 6-6 6"/>',
  sparkles:
    '<path d="M12 3l1.8 4.9L18.7 9.7l-4.9 1.8L12 16.4l-1.8-4.9L5.3 9.7l4.9-1.8z"/><path d="M18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  cpu:
    '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
  file:
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h4"/>',
  alert:
    '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  download:
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/>',
  broom:
    '<path d="M19 3l-7 7"/><path d="M13 6l5 5"/><path d="M11 9L4 16l4 4 7-7z"/><path d="M4 20l-1 1"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff:
    '<path d="M10.6 6.2A9.9 9.9 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-3.2 4M6.2 7.9A17 17 0 0 0 2 12s3.5 6 10 6c1.5 0 2.8-.3 4-.8"/><path d="M3 3l18 18"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  link: '<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>',
  zap: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  layers:
    '<path d="M12 2 2 7l10 5 10-5z"/><path d="M2 12l10 5 10-5M2 17l10 5 10-5"/>',
  // ---------- 法律主题图标 ----------
  scale:
    '<path d="M12 3v18"/><path d="M7 21h10"/><path d="M5 7h14"/><path d="M5 7 2 14h6z"/><path d="M19 7l-3 7h6z"/><circle cx="12" cy="4" r="1.4"/>',
  book:
    '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20"/>',
  briefcase:
    '<rect x="2.5" y="7" width="19" height="13" rx="2"/><path d="M8.5 7V5a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v2"/><path d="M2.5 12.5h19"/>',
  heart:
    '<path d="M12 20s-7.5-4.6-7.5-9.6A4.4 4.4 0 0 1 12 7a4.4 4.4 0 0 1 7.5 3.4C19.5 15.4 12 20 12 20z"/>',
  shield:
    '<path d="M12 2.5 4.5 5.5v6c0 5 3.2 8.6 7.5 10 4.3-1.4 7.5-5 7.5-10v-6z"/><path d="M9.2 12l2 2 3.6-3.8"/>',
  gavel:
    '<path d="M3 21h9"/><path d="M7.5 17 14 10.5"/><path d="M12 4.5 19.5 12l-2.5 2.5L9.5 7z"/><path d="M15 2l6 6"/>',
  folder:
    '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
}

const inner = computed(() => PATHS[props.name] || PATHS.message)
</script>
