<script setup lang="ts">
import { useEditorStore } from "../stores/editor";
import { useLabStore } from "../stores/lab";
import { useUiStore } from "../stores/ui";
const editor = useEditorStore(),
  lab = useLabStore(),
  ui = useUiStore();
</script>
<template>
  <form
    v-if="editor.annotationDraft"
    id="annotation-form"
    @input="editor.touchDraft"
    @submit.prevent="
      ui.run(() => {
        editor.commitDraft();
        ui.notify('注释已应用，保存项目后保留');
      })
    "
  >
    <div class="inspector-summary">
      <div class="large-icon">T</div>
      <div><b>画布注释</b><small>网段、区域与实验说明</small></div>
    </div>
    <label class="field"
      ><span>注释内容</span
      ><textarea
        id="annotation-text"
        v-model="editor.annotationDraft.text"
        rows="5"
        maxlength="1000"
        required
        :disabled="lab.locked"
      /><small>支持多行文字；拖动画布上的注释调整位置。</small></label
    >
    <label class="field"
      ><span>字号</span
      ><input
        id="annotation-font-size"
        v-model.number="editor.annotationDraft.fontSize"
        type="number"
        min="12"
        max="28"
        step="1"
        required
        :disabled="lab.locked"
    /></label>
    <label class="field"
      ><span>文字颜色</span
      ><input
        id="annotation-color"
        v-model="editor.annotationDraft.color"
        type="color"
        :disabled="lab.locked"
    /></label>
    <label class="field"
      ><span>背景</span
      ><select
        id="annotation-background"
        v-model="editor.annotationDraft.background"
        :disabled="lab.locked"
        @change="editor.touchDraft"
      >
        <option value="#fff7d6">浅黄</option>
        <option value="#e8f1ff">浅蓝</option>
        <option value="#e8f8ee">浅绿</option>
        <option value="#f3eaff">浅紫</option>
        <option value="none">透明</option>
        <option
          v-if="
            !['#fff7d6', '#e8f1ff', '#e8f8ee', '#f3eaff', 'none'].includes(
              editor.annotationDraft.background,
            )
          "
          :value="editor.annotationDraft.background"
        >
          自定义颜色
        </option>
      </select></label
    >
    <div class="inspector-actions">
      <button class="primary" type="submit" :disabled="lab.locked">
        应用注释</button
      ><button
        id="delete-annotation"
        type="button"
        class="delete-button"
        :disabled="lab.locked"
        @click="editor.deleteSelection"
      >
        删除注释
      </button>
    </div>
    <p class="inspector-help">
      注释仅用于说明，不配置设备地址；随项目 JSON 保存和导入导出。
    </p>
  </form>
</template>
