<script setup lang="ts">
import { computed, watch } from "vue";
import type { Device } from "../types/lab";
import { useLabStore } from "../stores/lab";
import { useUiStore } from "../stores/ui";
import SaveConfigButton from "./SaveConfigButton.vue";
const props = defineProps<{ node: Device }>();
const lab = useLabStore(),
  ui = useUiStore();
const status = computed(() => lab.configs[props.node.id]);
watch(
  () => [
    lab.documentVersion,
    lab.saved,
    props.node.id,
    lab.phase,
    lab.operation,
  ],
  () => {
    if (lab.saved && !lab.operation && !lab.busy)
      void ui.run(() => lab.loadConfig(props.node.id));
  },
  { immediate: true },
);
</script>

<template>
  <div class="property-section config-panel">
    <h3>设备配置</h3>
    <p class="inspector-help">
      终端配置完成后保存。清理设备会保留配置目录，重新部署自动加载。
    </p>
    <SaveConfigButton :node-id="node.id" />
    <p class="inspector-help" id="config-save-state">
      {{
        status?.persisted
          ? `共享配置已就绪${status.saved_at ? " · Web 保存：" + status.saved_at : ""}`
          : "首次部署时创建共享配置目录"
      }}
    </p>
    <details v-if="status?.persisted">
      <summary>查看磁盘配置</summary>
      <code class="code-line">{{ status.path }}</code>
      <code
        v-for="path in status.paths?.filter((path) => path !== status.path)"
        :key="path"
        class="code-line"
        >{{ path }}</code
      >
      <ul v-if="status.files?.length" class="config-files">
        <li v-for="file in status.files" :key="file.path">
          <code>{{ file.path }}</code
          ><span v-if="file.size !== undefined">{{ file.size }} B</span>
        </li>
      </ul>
      <p v-if="status.modified_at" class="inspector-help">
        文件更新：{{ new Date(status.modified_at * 1000).toLocaleString() }}
      </p>
      <textarea
        v-if="status.content"
        id="saved-device-config"
        :value="status.content"
        rows="9"
        readonly
        aria-label="已保存设备配置"
      ></textarea>
      <button
        type="button"
        :disabled="!!lab.operation || lab.busy"
        @click="ui.run(() => lab.loadConfig(node.id))"
      >
        刷新配置
      </button>
    </details>
  </div>
</template>

<style scoped>
textarea {
  width: 100%;
  margin: 10px 0;
  font: 12px/1.5 monospace;
  resize: vertical;
}
.code-line {
  overflow-wrap: anywhere;
  white-space: normal;
}
.config-files {
  padding: 0;
  list-style: none;
  font-size: 11px;
}
.config-files li {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  padding: 5px 0;
}
.config-files code {
  overflow-wrap: anywhere;
}
.config-files span {
  flex-shrink: 0;
  color: #78869a;
}
</style>
