<script setup lang="ts">
import { computed } from "vue";
import type { Device } from "../types/lab";
import {
  colors,
  nodeHeight,
  nodeWidth,
  portPoint,
  resizeNodeBounds,
  titles,
} from "../domain/topology";
import type { ResizeHandle } from "../domain/topology";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import DeviceIcon from "./DeviceIcon.vue";
import { useTerminalsStore } from "../stores/terminals";
const terminals = useTerminalsStore();
const props = defineProps<{ node: Device }>();
const ui = useUiStore();
const lab = useLabStore(),
  editor = useEditorStore();
const selected = computed(
  () =>
    editor.selected?.type === "node" && editor.selected.id === props.node.id,
);
const height = computed(() => nodeHeight(props.node));
const width = computed(() => nodeWidth(props.node));
const contentScale = computed(() =>
  Math.min(width.value / 128, height.value / 100),
);
const canResize = computed(
  () =>
    selected.value &&
    !lab.locked &&
    editor.mode === "select" &&
    !editor.pending,
);
const handleUnit = computed(() => 1 / editor.view.scale);
const handleGap = computed(() => 4 + 10 * handleUnit.value);
const handles: {
  direction: ResizeHandle;
  x: number;
  y: number;
  label: string;
}[] = [
  { direction: "nw", x: -1, y: -1, label: "左上" },
  { direction: "n", x: 0, y: -1, label: "上" },
  { direction: "ne", x: 1, y: -1, label: "右上" },
  { direction: "e", x: 1, y: 0, label: "右" },
  { direction: "se", x: 1, y: 1, label: "右下" },
  { direction: "s", x: 0, y: 1, label: "下" },
  { direction: "sw", x: -1, y: 1, label: "左下" },
  { direction: "w", x: -1, y: 0, label: "左" },
];
function resizeWithKey(event: KeyboardEvent, handle: ResizeHandle) {
  if (!canResize.value) return;
  const step = event.shiftKey ? 24 : 6;
  const delta = {
    x:
      event.key === "ArrowRight" ? step : event.key === "ArrowLeft" ? -step : 0,
    y: event.key === "ArrowDown" ? step : event.key === "ArrowUp" ? -step : 0,
  };
  if (!delta.x && !delta.y) return;
  event.preventDefault();
  lab.resizeNode(props.node.id, resizeNodeBounds(props.node, handle, delta));
}
const ports = computed(() =>
  props.node.ports.map((port) => ({
    ...port,
    ...portPoint(props.node, port.name),
  })),
);
</script>

<template>
  <g
    class="topology-node"
    :class="{ selected }"
    :transform="`translate(${node.x} ${node.y})`"
    :data-node="node.id"
    tabindex="0"
    role="button"
    :aria-label="`${node.name} ${titles[node.kind]}`"
    @dblclick.stop="ui.run(() => terminals.open(node.id))"
    @keydown.enter.stop="
      ui.run(() => editor.select({ type: 'node', id: node.id }))
    "
  >
    <rect
      class="node-body"
      :x="-width / 2"
      :y="-height / 2"
      :width="width"
      :height="height"
      rx="11"
    />
    <circle
      :cx="width / 2 - 15"
      :cy="-height / 2 + 12"
      r="3"
      :fill="lab.phase === 'running' ? '#49b08c' : '#d4dce8'"
    />
    <g :transform="`scale(${contentScale})`" class="node-content">
      <g transform="translate(-17 -35)" :color="colors[node.kind]"
        ><DeviceIcon :kind="node.kind" width="34" height="34"
      /></g>
      <text class="node-name" y="19">{{ node.name }}</text
      ><text class="node-kind" y="35">{{ titles[node.kind] }}</text>
    </g>
    <g v-for="port in ports" :key="port.name">
      <circle
        class="port"
        :class="{
          used: !!lab.getConnection(node.id, port.name),
          pending:
            editor.pending?.node === node.id &&
            editor.pending.port === port.name,
        }"
        :cx="port.x - node.x"
        :cy="port.y - node.y"
        r="4"
        :data-port="port.name"
        :data-node="node.id"
      >
        <title>
          {{ node.name }}.{{ port.name }} →
          {{ lab.peerLabel(node.id, port.name) }}
        </title>
      </circle>
      <text
        v-if="selected || editor.mode === 'connect'"
        class="port-label"
        :x="
          port.x -
          node.x +
          port.side * (canResize ? handleGap + 12 * handleUnit : 9)
        "
        :y="port.y - node.y + 3"
        :text-anchor="port.side < 0 ? 'end' : 'start'"
        >{{ port.name }}</text
      >
    </g>
    <g v-if="canResize" class="node-resize-controls" @dblclick.stop>
      <rect
        class="node-resize-outline"
        :x="-width / 2 - handleGap"
        :y="-height / 2 - handleGap"
        :width="width + 2 * handleGap"
        :height="height + 2 * handleGap"
        vector-effect="non-scaling-stroke"
      />
      <g
        v-for="handle in handles"
        :key="handle.direction"
        class="node-resize-handle"
        :data-resize="handle.direction"
        :transform="`translate(${handle.x * (width / 2 + handleGap)} ${handle.y * (height / 2 + handleGap)})`"
        :style="{ cursor: `${handle.direction}-resize` }"
        tabindex="0"
        role="button"
        :aria-label="`${handle.label}侧调整大小，使用方向键微调`"
        @keydown.stop="ui.run(() => resizeWithKey($event, handle.direction))"
      >
        <title>拖动{{ handle.label }}侧调整大小；方向键微调，Shift 加速</title>
        <rect
          class="node-resize-hit"
          :x="-9 * handleUnit"
          :y="-9 * handleUnit"
          :width="18 * handleUnit"
          :height="18 * handleUnit"
        />
        <rect
          class="node-resize-grip"
          :x="-4 * handleUnit"
          :y="-4 * handleUnit"
          :width="8 * handleUnit"
          :height="8 * handleUnit"
          :rx="handleUnit"
          vector-effect="non-scaling-stroke"
        />
      </g>
    </g>
  </g>
</template>
