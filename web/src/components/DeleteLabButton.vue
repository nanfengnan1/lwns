<script setup lang="ts">
import { computed } from "vue";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";

const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
const empty = computed(
  () => !lab.saved && !editor.unsaved && !lab.topology.nodes.length,
);
async function remove() {
  lab.assertEditable();
  if (empty.value) return;
  const saved = lab.saved;
  const message = saved
    ? `删除实验“${lab.topology.name}”？实验文件和当前未保存的修改都会删除。`
    : `删除未保存的实验“${lab.topology.name}”？当前画布和未保存的设备设置将被丢弃。`;
  if (!window.confirm(message)) return;
  await lab.deleteLab();
  ui.notify(saved ? "实验已删除" : "未保存的实验已删除");
}
</script>

<template>
  <button
    type="button"
    class="delete-button"
    :disabled="lab.locked || empty"
    :title="
      lab.locked
        ? '请等待操作完成，并清理设备后再删除实验'
        : empty
          ? '当前画布为空'
          : lab.saved
            ? '删除当前实验文件及未保存修改'
            : '删除当前未保存的实验'
    "
    aria-label="删除当前实验"
    @click="ui.run(remove)"
  >
    <slot>{{ lab.saved ? "删除实验文件" : "删除未保存实验" }}</slot>
  </button>
</template>
