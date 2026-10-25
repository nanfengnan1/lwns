<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from "vue";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import { useTerminalsStore } from "../stores/terminals";
import type { TerminalControls } from "../types/terminal";

const DeviceTerminal = defineAsyncComponent(
  () => import("./DeviceTerminal.vue"),
);

const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore(),
  terminals = useTerminalsStore();
const nodeId = ref("");
const components = new Map<string, TerminalControls>();
const current = computed(() =>
  terminals.tabs.find((tab) => tab.id === terminals.active),
);
const canOpen = computed(() => lab.canOpenTerminal(nodeId.value));
const states = {
  connecting: "连接中",
  connected: "已连接",
  disconnected: "已断开",
};
watch(
  () => editor.node?.id,
  (id) => {
    if (id && lab.getRuntimeNode(id)) nodeId.value = id;
  },
);
watch(
  () => lab.runningNodes.map((node) => node.id),
  (ids) => {
    if (!ids.includes(nodeId.value)) nodeId.value = ids[0] || "";
  },
  { immediate: true },
);
</script>

<template>
  <div id="console" @keydown.stop>
    <div class="terminal-toolbar">
      <select id="terminal-node" v-model="nodeId" aria-label="终端设备">
        <option
          v-for="node in lab.runningNodes"
          :key="node.id"
          :value="node.id"
        >
          {{ node.name }}
        </option>
      </select>
      <button
        id="open-terminal"
        :disabled="!canOpen"
        @click="ui.run(() => terminals.open(nodeId))"
      >
        打开终端
      </button>
      <button
        v-if="lab.getRuntimeNode(nodeId)?.kind === 'router'"
        :disabled="!canOpen"
        @click="ui.run(() => terminals.open(nodeId, 'shell'))"
      >
        Linux Shell
      </button>
      <span class="panel-spacer"></span>
      <span v-if="current" class="terminal-state" :class="current.state">{{
        states[current.state]
      }}</span>
      <button
        :disabled="!current || current.state !== 'disconnected'"
        @click="components.get(terminals.active)?.connect()"
      >
        重连
      </button>
      <button
        :disabled="!current"
        @click="components.get(terminals.active)?.clear()"
      >
        清屏
      </button>
    </div>
    <div
      v-if="terminals.tabs.length"
      class="terminal-tabs"
      role="tablist"
      aria-label="设备终端"
    >
      <div
        v-for="tab in terminals.tabs"
        :key="tab.id"
        class="terminal-tab"
        :class="{ active: terminals.active === tab.id }"
      >
        <button
          role="tab"
          :aria-selected="terminals.active === tab.id"
          @click="terminals.active = tab.id"
        >
          <i class="terminal-dot" :class="tab.state"></i>{{ tab.name
          }}<small>{{ tab.mode === "shell" ? "sh" : "vtysh" }}</small>
        </button>
        <button
          class="close-terminal"
          :aria-label="`关闭 ${tab.name} ${tab.mode === 'shell' ? 'sh' : 'vtysh'} 终端`"
          @click="terminals.close(tab.id)"
        >
          ×
        </button>
      </div>
    </div>
    <div
      v-if="!terminals.tabs.length"
      id="terminal-empty"
      class="terminal-empty"
    >
      <b>&gt;_ 设备终端</b>
      <span>{{
        lab.environment.ready
          ? "双击已部署设备，或选择设备后打开终端。"
          : "部署到 Linux Docker 主机后，即可在网页中操作设备。"
      }}</span>
      <small>实时输出 · Tab 补全 · Ctrl+C 中断 · 多设备标签</small>
    </div>
    <DeviceTerminal
      v-for="tab in terminals.tabs"
      :key="tab.id"
      :ref="
        (component) => {
          if (component)
            components.set(tab.id, component as unknown as TerminalControls);
          else components.delete(tab.id);
        }
      "
      v-show="terminals.active === tab.id"
      :tab="tab"
      :active="
        terminals.active === tab.id && ui.panel === 'console' && !ui.collapsed
      "
      @state="tab.state = $event"
    />
  </div>
</template>
