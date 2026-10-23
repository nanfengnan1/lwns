<script setup lang="ts">
import { ref } from "vue";
import type { AlignMode } from "../domain/canvas";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import SaveConfigButton from "./SaveConfigButton.vue";
const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
const alignMode = ref<AlignMode>("layers");
function align() {
  editor.commitDraft();
  lab.autoAlign(alignMode.value);
  editor.pending = null;
  editor.fitRevision++;
  ui.notify("设备已自动对齐，注释保留原位置；保存后保留布局");
}
async function save() {
  editor.commitDraft();
  await lab.save();
  ui.notify(lab.runtime?.deployment ? "布局已保存" : "拓扑已保存");
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
      <button id="save" :disabled="lab.layoutLocked" @click="ui.run(save)">
        {{ lab.runtime?.deployment ? "保存布局" : "保存" }}
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
  <div class="canvas-toolbar" aria-label="拓扑排版工具">
    <label for="align-mode">排版</label>
    <select
      id="align-mode"
      v-model="alignMode"
      :disabled="lab.layoutLocked"
      aria-label="自动对齐方式"
    >
      <option value="layers">智能分层</option>
      <option value="horizontal">水平排列</option>
      <option value="vertical">垂直排列</option>
      <option value="grid">网格排列</option>
    </select>
    <button
      id="auto-align"
      :disabled="lab.layoutLocked || lab.topology.nodes.length < 2"
      @click="ui.run(align)"
    >
      自动对齐
    </button>
    <button
      id="optimize-links"
      :disabled="lab.layoutLocked"
      :aria-pressed="lab.topology.optimizeLinks !== false"
      :class="{ active: lab.topology.optimizeLinks !== false }"
      title="就近选择图形端口并缩短连线，优先绕开设备；实际接口关系保持不变"
      @click="
        ui.run(() =>
          lab.setLinkOptimization(lab.topology.optimizeLinks === false),
        )
      "
    >
      连线优化 {{ lab.topology.optimizeLinks !== false ? "已开启" : "已关闭" }}
    </button>
    <button
      id="add-annotation"
      :disabled="lab.locked || (lab.topology.annotations?.length || 0) >= 100"
      :aria-pressed="editor.mode === 'annotation'"
      :class="{ active: editor.mode === 'annotation' }"
      @click="
        editor.setMode(editor.mode === 'annotation' ? 'select' : 'annotation')
      "
    >
      ＋ 添加注释
    </button>
  </div>
</template>
