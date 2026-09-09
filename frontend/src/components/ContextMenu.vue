<script setup>
import { onBeforeUnmount, onMounted } from 'vue'

const props = defineProps({ menu: { type: Object, default: null } })
const emit = defineEmits(['select', 'close'])

function closeOnKeyboard(event) { if (event.key === 'Escape') emit('close') }
function closeOnPointer(event) {
  if (!event.target.closest?.('.context-menu')) emit('close')
}
function closeOnScroll() { emit('close') }
onMounted(() => {
  window.addEventListener('keydown', closeOnKeyboard)
  window.addEventListener('pointerdown', closeOnPointer)
  window.addEventListener('scroll', closeOnScroll, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', closeOnKeyboard)
  window.removeEventListener('pointerdown', closeOnPointer)
  window.removeEventListener('scroll', closeOnScroll, true)
})
</script>

<template>
  <Teleport to="body">
    <menu v-if="menu" class="context-menu" :style="{ left: `${menu.x}px`, top: `${menu.y}px` }" @contextmenu.prevent>
      <li v-for="item in menu.items" :key="item.id">
        <button :class="{ danger: item.danger }" :disabled="item.disabled" @click="emit('select', item.id)">
          <span v-if="item.icon">{{ item.icon }}</span>{{ item.label }}
          <small v-if="item.hint">{{ item.hint }}</small>
        </button>
      </li>
    </menu>
  </Teleport>
</template>

<style scoped>
.context-menu{position:fixed;z-index:9999;min-width:176px;margin:0;padding:5px;list-style:none;background:#fff;border:1px solid #dce2eb;border-radius:9px;box-shadow:0 12px 32px #17243a26}.context-menu li{margin:0}.context-menu button{width:100%;display:flex;align-items:center;gap:8px;border:0;border-radius:6px;padding:8px 9px;background:transparent;color:#455369;text-align:left;font-size:11px;cursor:pointer}.context-menu button:hover:not(:disabled){background:#f0f1ff;color:#4d4fbb}.context-menu button:disabled{cursor:not-allowed;color:#a1aab7}.context-menu button.danger{color:#b15b51}.context-menu button span{width:14px;color:#7779cf}.context-menu button small{margin-left:auto;color:#99a4b2;font-size:8px}
</style>
