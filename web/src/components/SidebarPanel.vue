<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  SIDEBAR_LIMITS,
  useLayoutStore,
  type SidebarSide,
} from "../stores/layout";

const props = defineProps<{ side: SidebarSide; title: string }>();
const layout = useLayoutStore();
const collapsed = computed(() => layout.sides[props.side].collapsed);
const toggleLabel = computed(
  () => `${collapsed.value ? "展开" : "收起"}${props.title}`,
);
const resizing = ref(false);
let drag: {
  pointer: number;
  x: number;
  width: number;
  handle: HTMLElement;
} | null = null;
function begin(event: PointerEvent) {
  if (event.button !== 0 || drag || collapsed.value) return;
  event.preventDefault();
  const handle = event.currentTarget as HTMLElement;
  drag = {
    pointer: event.pointerId,
    x: event.clientX,
    width: layout.widths[props.side],
    handle,
  };
  handle.setPointerCapture(event.pointerId);
  handle.focus({ preventScroll: true });
  resizing.value = true;
  document.documentElement.classList.add("resizing-sidebar");
}
function move(event: PointerEvent) {
  if (!drag || event.pointerId !== drag.pointer) return;
  layout.setWidth(
    props.side,
    drag.width + (event.clientX - drag.x) * (props.side === "left" ? 1 : -1),
  );
}
function end() {
  const active = drag;
  drag = null;
  resizing.value = false;
  if (active) {
    document.documentElement.classList.remove("resizing-sidebar");
    if (active.handle.hasPointerCapture(active.pointer))
      active.handle.releasePointerCapture(active.pointer);
  }
}
function toggle() {
  end();
  layout.toggle(props.side);
}
function keyboard(event: KeyboardEvent) {
  const step = (event.shiftKey ? 40 : 10) * (props.side === "left" ? 1 : -1);
  const next = (
    {
      ArrowLeft: layout.widths[props.side] - step,
      ArrowRight: layout.widths[props.side] + step,
      Home: SIDEBAR_LIMITS[props.side].min,
      End: layout.maxWidth(props.side),
    } as Record<string, number>
  )[event.key];
  if (next === undefined) return;
  event.preventDefault();
  layout.setWidth(props.side, next);
}
onMounted(() => window.addEventListener("blur", end));
onBeforeUnmount(() => {
  end();
  window.removeEventListener("blur", end);
});
</script>

<template>
  <div
    class="sidebar-panel"
    :class="[side, { 'is-collapsed': collapsed, resizing }]"
  >
    <button
      :id="`toggle-${side}-sidebar`"
      class="sidebar-toggle"
      :title="toggleLabel"
      :aria-label="toggleLabel"
      :aria-expanded="!collapsed"
      :aria-controls="`${side}-sidebar-content`"
      @click="toggle"
    >
      <span aria-hidden="true">{{
        (side === "left") !== collapsed ? "‹" : "›"
      }}</span>
      <span v-if="collapsed" class="sidebar-rail-label">{{ title }}</span>
    </button>
    <div
      v-show="!collapsed"
      :id="`${side}-sidebar-content`"
      class="sidebar-content"
    >
      <slot />
    </div>
    <div
      v-show="!collapsed"
      :id="`${side}-sidebar-resize`"
      class="sidebar-resize"
      role="separator"
      aria-orientation="vertical"
      :aria-label="`调整${title}宽度`"
      :aria-controls="`${side}-sidebar-content`"
      :aria-valuemin="SIDEBAR_LIMITS[side].min"
      :aria-valuemax="layout.maxWidth(side)"
      :aria-valuenow="layout.widths[side]"
      :aria-valuetext="`${layout.widths[side]} 像素`"
      tabindex="0"
      title="左右拖动调整宽度 · 双击恢复默认 · 方向键微调"
      @pointerdown="begin"
      @pointermove="move"
      @pointerup="end"
      @pointercancel="end"
      @lostpointercapture="end"
      @dblclick="layout.reset(side)"
      @keydown.stop="keyboard"
    >
      <span></span>
    </div>
  </div>
</template>
