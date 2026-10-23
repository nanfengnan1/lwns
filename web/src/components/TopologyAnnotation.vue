<script setup lang="ts">
import { computed } from "vue";
import type { Annotation } from "../types/lab";
import { annotationBox } from "../domain/canvas";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
const props = defineProps<{ note: Annotation }>();
const editor = useEditorStore(),
  ui = useUiStore();
const box = computed(() => annotationBox(props.note));
const selected = computed(
  () =>
    editor.selected?.type === "annotation" &&
    editor.selected.id === props.note.id,
);
</script>
<template>
  <g
    class="topology-annotation"
    :class="{ selected }"
    :data-annotation="note.id"
    :transform="`translate(${note.x} ${note.y})`"
    tabindex="0"
    role="button"
    :aria-label="`注释：${note.text}`"
    @keydown.enter.stop="
      ui.run(() => editor.select({ type: 'annotation', id: note.id }))
    "
  >
    <rect
      class="annotation-body"
      :width="box.width"
      :height="box.height"
      rx="6"
      :fill="note.background === 'none' ? 'transparent' : note.background"
    />
    <text :fill="note.color" :font-size="note.fontSize" class="annotation-text">
      <tspan
        v-for="(line, index) in box.lines"
        :key="index"
        x="12"
        :y="10 + note.fontSize + index * note.fontSize * 1.5"
        >{{ line }}</tspan
      >
    </text>
  </g>
</template>
