<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import { projectName } from "../domain/topology";
const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
const dialog = ref<HTMLDialogElement>(),
  input = ref<HTMLInputElement>();
const name = ref(""),
  error = ref(""),
  submitting = ref(false);
watch(
  () => ui.labDialogMode,
  async (mode) => {
    if (!mode) {
      dialog.value?.close();
      return;
    }
    name.value = mode === "new" ? "" : lab.topology.name;
    error.value = "";
    await nextTick();
    dialog.value?.showModal();
    input.value?.focus();
    input.value?.select();
  },
  { flush: "post" },
);
function close() {
  if (!submitting.value) ui.labDialogMode = null;
}
async function submit() {
  if (submitting.value || lab.operation || !ui.labDialogMode) return;
  error.value = "";
  try {
    const value = projectName(name.value),
      mode = ui.labDialogMode;
    if (mode === "new" && !editor.discardOK()) return;
    submitting.value = true;
    if (mode === "new") {
      lab.newLab(value);
      ui.notify("项目已创建，添加设备后可保存拓扑");
    } else {
      await lab.rename(value);
      ui.notify(
        lab.saved ? "项目名称已保存" : "项目已命名，保存拓扑后写入后端",
      );
    }
    ui.labDialogMode = null;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <dialog
    id="project-name-dialog"
    ref="dialog"
    aria-labelledby="project-name-heading"
    @cancel.prevent="close"
    @close="close"
  >
    <form @submit.prevent="submit">
      <div class="dialog-top">
        <h2 id="project-name-heading">
          {{ ui.labDialogMode === "new" ? "新建项目" : "重命名项目" }}
        </h2>
        <button
          type="button"
          aria-label="关闭项目名称窗口"
          :disabled="submitting"
          @click="close"
        >
          ×
        </button>
      </div>
      <label class="field"
        ><span>项目名称</span>
        <input
          id="project-name-input"
          ref="input"
          v-model="name"
          maxlength="80"
          required
          autocomplete="off"
          placeholder="例如：OSPF 双网段实验"
          :disabled="submitting"
          aria-describedby="project-name-help project-name-error"
        />
      </label>
      <p id="project-name-help">
        支持中文，最多 80 个字符。{{
          ui.labDialogMode === "new"
            ? "创建后点击“保存”写入后端。"
            : "改名保留原项目 ID、设备配置和部署状态。"
        }}
      </p>
      <p v-if="error" id="project-name-error" class="error-text" role="alert">
        {{ error }}
      </p>
      <button
        id="confirm-project-name"
        class="primary"
        type="submit"
        :disabled="submitting || !!lab.operation"
      >
        {{
          submitting
            ? "处理中…"
            : ui.labDialogMode === "new"
              ? "创建项目"
              : "确认改名"
        }}
      </button>
      <button
        type="button"
        class="project-name-cancel"
        :disabled="submitting"
        @click="close"
      >
        取消
      </button>
    </form>
  </dialog>
</template>

<style scoped>
.project-name-cancel {
  width: 100%;
  margin-top: 8px;
}
</style>
