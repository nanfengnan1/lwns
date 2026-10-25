<script setup lang="ts">
import { computed } from "vue";
import type { Device } from "../types/lab";
import { colors, titles } from "../domain/topology";
import { nodeRadius, type Anchor } from "../domain/canvas";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import { useTerminalsStore } from "../stores/terminals";
import DeviceIcon from "./DeviceIcon.vue";

const props = defineProps<{ node: Device; anchors: Record<string, Anchor> }>();
const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore(),
  terminals = useTerminalsStore();
const selected = computed(
  () =>
    editor.selected?.type === "node" && editor.selected.id === props.node.id,
);
const radius = computed(() => nodeRadius(props.node));
const ports = computed(() =>
  props.node.ports.map((port) => ({ ...port, ...props.anchors[port.name] })),
);
</script>

<template>
  <g
    class="topology-node"
    :class="{ selected }"
    :transform="'translate(' + node.x + ' ' + node.y + ')'"
    :data-node="node.id"
    tabindex="0"
    role="button"
    :aria-label="node.name + ' ' + titles[node.kind]"
    @dblclick.stop="ui.run(() => terminals.open(node.id))"
    @keydown.enter.stop="
      ui.run(() => editor.select({ type: 'node', id: node.id }))
    "
  >
    <title>{{ node.name }} · {{ titles[node.kind] }}</title>
    <circle class="node-body" :r="radius" />
    <g
      transform="translate(-20 -20)"
      :color="colors[node.kind]"
      class="node-content"
    >
      <DeviceIcon :kind="node.kind" width="40" height="40" />
    </g>
    <circle
      :cx="radius * 0.65"
      :cy="-radius * 0.65"
      r="3"
      :fill="
        lab.phase === 'running' && lab.getRuntimeNode(node.id)
          ? '#49b08c'
          : '#d4dce8'
      "
    />
    <text class="node-name" :y="radius + 18">{{
      node.name.length > 14 ? node.name.slice(0, 13) + "…" : node.name
    }}</text>
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
        r="3.5"
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
        :x="port.x - node.x + port.dx * 11"
        :y="port.y - node.y + port.dy * 11 + (port.dy > 0.8 ? 3 : -2)"
        :text-anchor="
          port.dx < -0.3 ? 'end' : port.dx > 0.3 ? 'start' : 'middle'
        "
        >{{ port.name }}</text
      >
    </g>
  </g>
</template>
