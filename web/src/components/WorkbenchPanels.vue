<script setup lang="ts">
import { computed, ref } from "vue";
import { useLabStore } from "../stores/lab";
import { useUiStore } from "../stores/ui";
import { usePanelResize } from "../composables/usePanelResize";
import TerminalWorkspace from "./TerminalWorkspace.vue";
const lab = useLabStore(),
  ui = useUiStore();
const panelElement = ref<HTMLElement>();
const expanded = ref(false);
const {
  height,
  maxHeight,
  minHeight,
  resizing,
  beginResize,
  resize,
  endResize,
  resetHeight,
  keyResize,
} = usePanelResize(panelElement);
const logs = computed(() => lab.runtime?.logs || []);
async function refresh() {
  await lab.refreshEnvironment();
  ui.notify("运行状态与本机镜像已刷新");
}
</script>

<template>
  <section
    ref="panelElement"
    class="bottom-panel"
    :class="{ resizing, expanded }"
  >
    <div
      v-show="!ui.collapsed && !expanded"
      id="panel-resize-handle"
      class="panel-resize-handle"
      role="separator"
      aria-orientation="horizontal"
      aria-label="调整日志与设备终端面板高度"
      aria-controls="panel-body"
      :aria-valuemin="minHeight"
      :aria-valuemax="maxHeight"
      :aria-valuenow="height"
      :aria-valuetext="`${height} 像素`"
      tabindex="0"
      title="上下拖动调整高度 · 双击恢复默认 · 方向键微调"
      @pointerdown="beginResize"
      @pointermove="resize"
      @pointerup="endResize"
      @pointercancel="endResize"
      @lostpointercapture="endResize"
      @dblclick="resetHeight"
      @keydown.stop="keyResize"
    >
      <span></span>
    </div>
    <div class="panel-tabs">
      <button
        id="logs-tab"
        :class="{ active: ui.panel === 'logs' }"
        @click="ui.showPanel('logs')"
      >
        部署日志 <span id="log-count">{{ logs.length }}</span></button
      ><button
        id="console-tab"
        :class="{ active: ui.panel === 'console' }"
        @click="ui.showPanel('console')"
      >
        设备终端</button
      ><span class="panel-spacer"></span
      ><button
        id="expand-panel"
        :title="expanded ? '恢复面板' : '放大面板'"
        :aria-label="expanded ? '恢复面板' : '放大面板'"
        @click="
          expanded = !expanded;
          ui.collapsed = false;
        "
      >
        {{ expanded ? "恢复" : "放大" }}</button
      ><button id="refresh" title="刷新实际运行状态" @click="ui.run(refresh)">
        ↻ 刷新状态</button
      ><button
        id="toggle-panel"
        :title="ui.collapsed ? '展开面板' : '收起面板'"
        :aria-label="ui.collapsed ? '展开面板' : '收起面板'"
        :aria-expanded="!ui.collapsed"
        aria-controls="panel-body"
        @click="
          ui.collapsed = !ui.collapsed;
          if (ui.collapsed) expanded = false;
        "
      >
        {{ ui.collapsed ? "⌃" : "⌄" }}
      </button>
    </div>
    <div
      id="panel-body"
      class="panel-body"
      :class="{ collapsed: ui.collapsed }"
      :style="{ height: `${height}px` }"
    >
      <div id="logs" :hidden="ui.panel !== 'logs'">
        <div
          v-for="(log, index) in logs"
          :key="index"
          class="log-line"
          :class="{ error: /失败|错误/.test(log.message) }"
        >
          <time>{{ log.time.slice(11, 19) }}</time
          ><span>{{ log.message }}</span>
        </div>
        <div v-if="!logs.length" class="log-empty">
          <span>○</span>
          <div>
            拓扑已准备好，等待部署。<small>{{
              lab.environment.ready
                ? "保存拓扑后，点击「部署实验」创建容器和 veth 链路。"
                : "当前可以编辑和保存拓扑；真实部署需要连接 Linux Docker 主机。"
            }}</small>
          </div>
        </div>
        <div v-if="lab.runtime?.error" class="log-line error">
          <span>{{ lab.runtime.error }}</span>
        </div>
      </div>
      <TerminalWorkspace v-show="ui.panel === 'console'" />
    </div>
  </section>
</template>
