<script setup lang="ts">
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import SaveConfigButton from "./SaveConfigButton.vue";
import { useProjectFiles } from "../composables/useProjectFiles";
const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
const { save, applyTopology } = useProjectFiles();
function revealCommand(event: FocusEvent) {
  const target = event.target;
  if (target instanceof HTMLElement && target !== event.currentTarget) {
    target.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}
function align() {
  editor.commitDraft();
  const moved = lab.autoAlign();
  editor.pending = null;
  ui.notify(
    moved
      ? `已自动对齐 ${moved} 台设备，保存后保留布局`
      : "自动对齐完成，没有需要调整的相邻行列",
  );
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
    <div
      class="lab-command-scroll"
      tabindex="0"
      role="region"
      @focusin="revealCommand"
      aria-label="实验操作栏，空间不足时可横向滚动"
      title="空间不足时可左右滚动查看全部操作"
    >
      <div class="lab-command-row">
        <div class="lab-title">
          <button
            id="lab-name"
            class="lab-name-button"
            :title="`重命名项目：${lab.topology.name}`"
            aria-label="重命名项目"
            :disabled="!lab.canRename"
            @click="ui.labDialogMode = 'rename'"
          >
            <span class="lab-name-text">{{ lab.topology.name }}</span
            ><small aria-hidden="true">✎</small>
          </button>
          <span
            id="save-state"
            :class="{ dirty: editor.unsaved || lab.saveWarning }"
            :title="lab.saveWarning"
            >{{
              lab.operation === "save"
                ? "保存中…"
                : lab.operation === "update" || lab.phase === "updating"
                  ? "正在应用…"
                  : lab.runtime?.deployment && lab.phase === "error"
                    ? "操作失败，需清理"
                    : lab.pendingUpdate ||
                        (lab.runtime?.deployment &&
                          editor.draftDirty &&
                          editor.draft)
                      ? "拓扑待应用"
                      : editor.unsaved
                        ? "有未保存修改"
                        : lab.saveWarning || (lab.saved ? "已保存" : "未保存")
            }}</span
          >
        </div>
        <div class="canvas-toolbar" role="group" aria-label="拓扑排版工具">
          <button
            id="auto-align"
            :disabled="lab.layoutLocked || lab.topology.nodes.length < 2"
            title="将位置接近的设备对齐到同一行或列，保留整体布局"
            @click="ui.run(align)"
          >
            <svg
              class="button-icon"
              viewBox="0 0 20 20"
              fill="none"
              aria-hidden="true"
            >
              <path d="M3 3v14M6 5h10v4H6Zm0 7h7v4H6Z" /></svg
            >自动对齐
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
            连线优化
            {{ lab.topology.optimizeLinks !== false ? "已开启" : "已关闭" }}
          </button>
          <button
            id="add-annotation"
            :disabled="
              lab.locked || (lab.topology.annotations?.length || 0) >= 100
            "
            :aria-pressed="editor.mode === 'annotation'"
            :class="{ active: editor.mode === 'annotation' }"
            @click="
              editor.setMode(
                editor.mode === 'annotation' ? 'select' : 'annotation',
              )
            "
          >
            <svg
              class="button-icon"
              viewBox="0 0 20 20"
              fill="none"
              aria-hidden="true"
            >
              <path d="M3 3h14v10l-4 4H3Zm10 14v-4h4M6 7h8M6 10h5" /></svg
            >添加注释
          </button>
        </div>
        <div class="toolbar-actions" role="group" aria-label="实验保存与部署">
          <button
            id="save"
            :disabled="lab.layoutLocked || lab.pendingUpdate"
            :title="
              lab.pendingUpdate
                ? '设备或连线已修改，请点击应用拓扑'
                : `保存项目到 ${lab.serverHost}，同时保存运行中受支持设备的配置`
            "
            @click="ui.run(save)"
          >
            <svg
              class="button-icon"
              viewBox="0 0 20 20"
              fill="none"
              aria-hidden="true"
            >
              <path d="M4 3h10l3 3v11H3V3Zm2 0v5h7V3M6 17v-5h8v5" />
            </svg>
            保存项目
          </button>
          <SaveConfigButton
            v-if="
              lab.topology.nodes.some(lab.supportsConfig) ||
              lab.runningNodes.some(lab.supportsConfig)
            "
          />
          <button
            id="destroy"
            class="danger-subtle"
            :disabled="!lab.canDestroy"
            @click="ui.run(destroy)"
          >
            <svg
              class="button-icon"
              viewBox="0 0 20 20"
              fill="none"
              aria-hidden="true"
            >
              <path d="M3 5h14M7 5V3h6v2M5 5l1 12h8l1-12M8 8v6m4-6v6" /></svg
            >清理设备
          </button>
          <button
            v-if="lab.runtime?.deployment"
            id="apply-topology"
            class="primary"
            :disabled="
              !lab.canUpdate ||
              (!lab.pendingUpdate && !(editor.draftDirty && editor.draft))
            "
            title="将设备和连线修改同步到运行中的实验"
            @click="ui.run(applyTopology)"
          >
            应用拓扑
          </button>
          <button
            v-else
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
    </div>
  </div>
</template>
