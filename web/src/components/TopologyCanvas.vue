<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import {
  nodeHeight,
  nodeWidth,
  phases,
  portPoint,
  resizeNodeBounds,
} from "../domain/topology";
import type { ResizeHandle } from "../domain/topology";
import type { Device, Point } from "../types/lab";
import TopologyNode from "./TopologyNode.vue";

const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
const canvas = ref<SVGSVGElement>();
const transform = computed(
  () =>
    `translate(${editor.view.x} ${editor.view.y}) scale(${editor.view.scale})`,
);
const edges = computed(() =>
  lab.topology.links.flatMap((link) => {
    const a = lab.getNode(link.a.node),
      b = lab.getNode(link.b.node);
    if (!a || !b) return [];
    const p = portPoint(a, link.a.port),
      q = portPoint(b, link.b.port),
      offset = Math.max(45, Math.abs(p.x - q.x) * 0.45);
    return [
      {
        id: link.id,
        d: `M ${p.x} ${p.y} C ${p.x + offset * p.side} ${p.y}, ${q.x + offset * q.side} ${q.y}, ${q.x} ${q.y}`,
        x: (p.x + q.x) / 2,
        y: (p.y + q.y) / 2 - 9,
      },
    ];
  }),
);
type Drag = { pointerId: number; start: Point } & (
  | { type: "pan"; x: number; y: number }
  | { type: "node"; id: string; x: number; y: number }
  | { type: "resize"; node: Device; handle: ResizeHandle }
);
let drag: Drag | null = null;
const activeResize = ref<ResizeHandle | null>(null);
function finishDrag() {
  const pointerId = drag?.pointerId;
  drag = null;
  activeResize.value = null;
  if (pointerId !== undefined && canvas.value?.hasPointerCapture(pointerId))
    canvas.value.releasePointerCapture(pointerId);
}
let observer: ResizeObserver | undefined;
function screenPoint(x: number, y: number): Point {
  const rect = canvas.value!.getBoundingClientRect();
  return {
    x: (x - rect.left - editor.view.x) / editor.view.scale,
    y: (y - rect.top - editor.view.y) / editor.view.scale,
  };
}
function fit() {
  if (!canvas.value) return;
  finishDrag();
  const rect = canvas.value.getBoundingClientRect(),
    nodes = lab.topology.nodes;
  if (!nodes.length) {
    Object.assign(editor.view, { x: 0, y: 0, scale: 1 });
    return;
  }
  const minX = Math.min(...nodes.map((n) => n.x - nodeWidth(n) / 2)) - 46,
    maxX = Math.max(...nodes.map((n) => n.x + nodeWidth(n) / 2)) + 46;
  const minY = Math.min(...nodes.map((n) => n.y - nodeHeight(n) / 2)) - 50,
    maxY = Math.max(...nodes.map((n) => n.y + nodeHeight(n) / 2)) + 40;
  const scale = Math.min(
    1.3,
    Math.max(
      0.25,
      Math.min(
        (rect.width - 80) / (maxX - minX),
        (rect.height - 95) / (maxY - minY),
      ),
    ),
  );
  Object.assign(editor.view, {
    scale,
    x: rect.width / 2 - ((minX + maxX) / 2) * scale,
    y: rect.height / 2 + 14 - ((minY + maxY) / 2) * scale,
  });
}
function zoom(factor: number, clientX?: number, clientY?: number) {
  if (!canvas.value || drag) return;
  const rect = canvas.value.getBoundingClientRect(),
    x = clientX ?? rect.left + rect.width / 2,
    y = clientY ?? rect.top + rect.height / 2;
  const point = screenPoint(x, y),
    scale = Math.max(0.25, Math.min(2.5, editor.view.scale * factor));
  Object.assign(editor.view, {
    scale,
    x: x - rect.left - point.x * scale,
    y: y - rect.top - point.y * scale,
  });
}
function pointerDown(event: PointerEvent) {
  if (drag || (event.button !== 0 && event.button !== 1)) return;
  const target = event.target as Element;
  const port = target.closest<SVGElement>("[data-port]");
  if (port && event.button === 0) {
    if (
      editor.choosePort({ node: port.dataset.node!, port: port.dataset.port! })
    )
      ui.notify("veth 网线已添加");
    return;
  }
  const element = target.closest<SVGElement>(".topology-node"),
    edge = target.closest<SVGElement>(".edge");
  if (element && event.button === 0) {
    const id = element.dataset.node!;
    editor.select({ type: "node", id });
    const node = lab.getNode(id)!;
    if (!lab.locked && editor.mode !== "connect") {
      const handle = target.closest<SVGElement>("[data-resize]")?.dataset
        .resize as ResizeHandle | undefined;
      drag = handle
        ? {
            type: "resize",
            node: { ...node },
            handle,
            pointerId: event.pointerId,
            start: screenPoint(event.clientX, event.clientY),
          }
        : {
            type: "node",
            id,
            pointerId: event.pointerId,
            start: screenPoint(event.clientX, event.clientY),
            x: node.x,
            y: node.y,
          };
      activeResize.value = handle ?? null;
    }
  } else if (edge && event.button === 0)
    editor.select({ type: "link", id: edge.dataset.link! });
  else {
    editor.select(null);
    drag = {
      type: "pan",
      pointerId: event.pointerId,
      start: { x: event.clientX, y: event.clientY },
      x: editor.view.x,
      y: editor.view.y,
    };
  }
  if (drag) canvas.value?.setPointerCapture(event.pointerId);
}
function pointerMove(event: PointerEvent) {
  if (!drag || event.pointerId !== drag.pointerId) return;
  if (drag.type === "pan") {
    editor.view.x = drag.x + event.clientX - drag.start.x;
    editor.view.y = drag.y + event.clientY - drag.start.y;
  } else {
    if (lab.locked) {
      finishDrag();
      return;
    }
    const point = screenPoint(event.clientX, event.clientY);
    if (drag.type === "resize") {
      lab.resizeNode(
        drag.node.id,
        resizeNodeBounds(drag.node, drag.handle, {
          x: Math.round(point.x - drag.start.x),
          y: Math.round(point.y - drag.start.y),
        }),
      );
    } else
      lab.moveNode(drag.id, {
        x: Math.round((drag.x + point.x - drag.start.x) / 6) * 6,
        y: Math.round((drag.y + point.y - drag.start.y) / 6) * 6,
      });
  }
}
function dragOver(event: DragEvent) {
  if (!lab.locked) {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  }
}
function drop(event: DragEvent) {
  const kind = event.dataTransfer?.getData("text/plain");
  if (
    kind &&
    lab.catalog.some((item) => item.id === kind || item.kind === kind)
  )
    editor.addNode(kind, screenPoint(event.clientX, event.clientY));
}
watch(
  () => editor.fitRevision,
  async () => {
    finishDrag();
    await nextTick();
    fit();
  },
);
onMounted(() => {
  window.addEventListener("blur", finishDrag);
  observer = new ResizeObserver((entries) => {
    const rect = entries[0]?.contentRect;
    if (rect)
      Object.assign(editor.viewport, {
        width: rect.width,
        height: rect.height,
      });
  });
  observer.observe(canvas.value!);
  fit();
});
onBeforeUnmount(() => {
  finishDrag();
  observer?.disconnect();
  window.removeEventListener("blur", finishDrag);
});
</script>

<template>
  <div
    id="canvas-wrap"
    class="canvas-wrap"
    @dragover="dragOver"
    @drop.prevent="ui.run(() => drop($event))"
  >
    <div class="canvas-controls">
      <div class="tool-group">
        <button
          id="select-tool"
          :class="{ active: editor.mode === 'select' }"
          title="选择 / 移动 (V)"
          aria-label="选择工具"
          @click="editor.setMode('select')"
        >
          ↖</button
        ><button
          id="connect-tool"
          :class="{ active: editor.mode === 'connect' }"
          :disabled="lab.locked"
          title="连接端口 (C)"
          aria-label="连线工具"
          @click="editor.setMode('connect')"
        >
          ⌁
        </button>
      </div>
      <span class="control-divider"></span
      ><button
        id="zoom-out"
        title="缩小"
        aria-label="缩小"
        @click="zoom(1 / 1.2)"
      >
        −</button
      ><span id="zoom-value">{{ Math.round(editor.view.scale * 100) }}%</span
      ><button id="zoom-in" title="放大" aria-label="放大" @click="zoom(1.2)">
        ＋</button
      ><button id="fit" title="适应画布" aria-label="适应画布" @click="fit">
        ⛶
      </button>
    </div>
    <div id="phase" class="canvas-badge" :class="lab.phase">
      <i
        class="status-dot"
        :class="{
          ready: lab.phase === 'running',
          warn: ['error', 'degraded'].includes(lab.phase),
        }"
      ></i
      >{{ phases[lab.phase] }}
    </div>
    <svg
      id="canvas"
      ref="canvas"
      :class="{
        'connect-mode': editor.mode === 'connect',
        'resizing-device': !!activeResize,
      }"
      :style="activeResize ? { cursor: `${activeResize}-resize` } : undefined"
      role="img"
      aria-label="网络拓扑画布，拖动设备调整位置，拖动选中设备的手柄调整大小，点击端口连接网线"
      tabindex="0"
      @pointerdown.prevent="ui.run(() => pointerDown($event))"
      @pointermove="pointerMove"
      @pointerup="finishDrag"
      @pointercancel="finishDrag"
      @lostpointercapture="finishDrag"
      @wheel.prevent="
        zoom(Math.exp(-$event.deltaY * 0.001), $event.clientX, $event.clientY)
      "
    >
      <defs>
        <pattern
          id="grid"
          width="24"
          height="24"
          patternUnits="userSpaceOnUse"
          :patternTransform="transform"
        >
          <circle cx="1" cy="1" r="1" fill="#dce2ec" />
        </pattern>
        <filter id="node-shadow" x="-30%" y="-30%" width="160%" height="170%">
          <feDropShadow
            dx="0"
            dy="4"
            stdDeviation="6"
            flood-color="#263958"
            flood-opacity=".07"
          />
        </filter>
      </defs>
      <rect width="100%" height="100%" fill="url(#grid)" />
      <g id="viewport" :transform="transform">
        <g id="edges">
          <g
            v-for="edge in edges"
            :key="edge.id"
            class="edge"
            :class="{
              selected:
                editor.selected?.type === 'link' &&
                editor.selected.id === edge.id,
              running: lab.phase === 'running',
            }"
            :data-link="edge.id"
          >
            <path class="wire" :d="edge.d" />
            <path class="hit-area" :d="edge.d" />
            <text :x="edge.x" :y="edge.y" text-anchor="middle">veth</text>
          </g>
        </g>
        <g id="nodes">
          <TopologyNode
            v-for="node in lab.topology.nodes"
            :key="node.id"
            :node="node"
          />
        </g>
      </g>
    </svg>
    <div id="empty-state" :hidden="!!lab.topology.nodes.length">
      <div>⌘</div>
      <h2>从一台设备开始</h2>
      <p>将左侧设备拖入画布，点击两个端口完成连线。</p>
      <button
        id="empty-example"
        :disabled="!!lab.operation"
        @click="editor.discardOK() && lab.loadExample()"
      >
        加载示例拓扑
      </button>
    </div>
    <div class="canvas-footer">
      <span id="canvas-hint">{{ editor.hint }}</span
      ><span id="counts"
        >{{ lab.topology.nodes.length }} 台设备 /
        {{ lab.topology.links.length }} 条链路</span
      >
    </div>
  </div>
</template>
