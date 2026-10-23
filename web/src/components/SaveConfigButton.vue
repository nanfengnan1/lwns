<script setup lang="ts">
import { useLabStore } from "../stores/lab";
import { useUiStore } from "../stores/ui";
const props = defineProps<{ nodeId?: string }>();
const lab = useLabStore(),
  ui = useUiStore();
async function save() {
  const results = await lab.saveConfigs(props.nodeId);
  const exported = results.some((item) => item.status?.shared === false);
  ui.notify(
    exported
      ? "配置已导出。清理并重新部署后，设备将使用共享目录。"
      : `已保存 ${results.length} 台设备配置，清理后重新部署会恢复。`,
  );
}
</script>

<template>
  <button
    :id="nodeId ? 'save-device-config' : 'save-all-configs'"
    type="button"
    :disabled="!lab.canSaveConfig(nodeId)"
    title="将设备当前运行配置写入宿主机共享目录，并同步拓扑中的启动配置"
    @click="ui.run(save)"
  >
    {{ lab.operation === "save-config" ? "保存配置中…" : "保存设备配置" }}
  </button>
</template>
