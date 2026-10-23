<script setup lang="ts">
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import SaveConfigButton from "./SaveConfigButton.vue";
const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
async function save() {
  editor.commitDraft();
  await lab.save();
  ui.notify("拓扑已保存");
}
async function deploy() {
  editor.commitDraft();
  await lab.startJob("deploy");
  editor.pending = null;
  ui.showPanel("logs");
}
async function destroy() {
  if (
    !confirm(
      "清理当前实验创建的容器和 veth？拓扑和已保存的设备配置会保留；未保存的运行配置会丢失。",
    )
  )
    return;
  await lab.startJob("destroy");
  ui.showPanel("logs");
}
</script>

<template>
  <div class="lab-toolbar">
    <div class="lab-title">
      <span class="document-icon">▤</span>
      <button
        id="lab-name"
        class="lab-name-button"
        :title="`重命名项目：${lab.topology.name}`"
        aria-label="重命名项目"
        :disabled="!lab.canRename"
        @click="ui.labDialogMode = 'rename'"
      >
        {{ lab.topology.name }}<small>✎</small>
      </button>
      <span id="save-state">{{
        lab.operation === "save"
          ? "保存中…"
          : editor.unsaved
            ? "有未保存修改"
            : lab.saved
              ? "已保存"
              : "未保存"
      }}</span>
    </div>
    <div class="toolbar-actions">
      <button id="save" :disabled="lab.locked" @click="ui.run(save)">
        保存
      </button>
      <SaveConfigButton v-if="lab.topology.nodes.some(lab.supportsConfig)" />
      <button
        id="destroy"
        class="danger-subtle"
        :disabled="!lab.canDestroy"
        @click="ui.run(destroy)"
      >
        清理设备
      </button>
      <button
        id="deploy"
        class="primary"
        :disabled="!lab.canDeploy"
        :title="
          lab.environment.ready
            ? '创建设备并连接网线'
            : lab.environment.errors.join('；')
        "
        @click="ui.run(deploy)"
      >
        <span>▶</span> 部署实验
      </button>
    </div>
  </div>
</template>
