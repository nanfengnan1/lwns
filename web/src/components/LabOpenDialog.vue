<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { api, ApiError } from "../api/client";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import type { LabSummary, Phase } from "../types/lab";

const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
const dialog = ref<HTMLDialogElement>(),
  searchInput = ref<HTMLInputElement>();
const search = ref(""),
  selected = ref(""),
  loading = ref(false),
  opening = ref(false),
  error = ref("");
let revision = 0;
function failed(reason: unknown) {
  error.value = reason instanceof Error ? reason.message : String(reason);
  if (reason instanceof ApiError && reason.status === 401) {
    ui.labOpen = false;
    ui.report(reason);
  }
}
const labels: Record<Phase, string> = {
  idle: "未部署",
  running: "运行中",
  deploying: "部署中",
  destroying: "清理中",
  error: "需要检查",
  degraded: "状态异常",
};
const matches = computed(() => {
  const query = search.value.trim().toLocaleLowerCase();
  return lab.labs.filter(
    (item) =>
      !query || `${item.name} ${item.id}`.toLocaleLowerCase().includes(query),
  );
});
const current = computed(() =>
  matches.value.find((item) => item.id === selected.value),
);

async function refresh() {
  const version = ++revision;
  loading.value = true;
  error.value = "";
  try {
    const records = await api<LabSummary[]>("/api/labs");
    if (version !== revision || !ui.labOpen) return;
    lab.labs = records;
    if (!records.some((item) => item.id === selected.value))
      selected.value = "";
  } catch (reason) {
    if (version !== revision || !ui.labOpen) return;
    failed(reason);
  } finally {
    if (version === revision) loading.value = false;
  }
}

function close() {
  if (opening.value) return;
  revision++;
  ui.labOpen = false;
}

async function openSelected(id = selected.value) {
  if (opening.value || loading.value || lab.operation || !id) return;
  if (!lab.labs.some((item) => item.id === id) || !editor.discardOK()) return;
  opening.value = true;
  error.value = "";
  try {
    await lab.load(id);
    ui.labOpen = false;
    ui.notify(`已打开实验“${lab.topology.name}”`);
  } catch (reason) {
    failed(reason);
  } finally {
    opening.value = false;
  }
}

watch(
  () => ui.labOpen,
  async (visible) => {
    if (!visible) {
      revision++;
      dialog.value?.close();
      return;
    }
    search.value = "";
    selected.value = lab.saved ? lab.topology.id : "";
    error.value = "";
    await nextTick();
    dialog.value?.showModal();
    searchInput.value?.focus();
    void refresh();
  },
  { flush: "post" },
);

function closed() {
  if (!dialog.value?.open) {
    ui.labOpen = false;
    document.getElementById("menu-experiment")?.focus();
  }
}
</script>

<template>
  <dialog
    id="open-lab-dialog"
    ref="dialog"
    aria-labelledby="open-lab-title"
    @cancel.prevent="close"
    @close="closed"
    @keydown.stop
  >
    <div class="dialog-top">
      <div>
        <h2 id="open-lab-title">打开实验</h2>
        <p class="open-lab-description">
          选择当前宿主机上已保存的实验，继续编辑或查看运行状态。
        </p>
      </div>
      <button
        type="button"
        aria-label="关闭打开实验窗口"
        :disabled="opening"
        @click="close"
      >
        ×
      </button>
    </div>
    <form @submit.prevent="openSelected()">
      <div class="open-lab-search-row">
        <input
          id="open-lab-search"
          ref="searchInput"
          v-model="search"
          type="search"
          placeholder="搜索实验名称或 ID"
          aria-label="搜索已保存实验"
          :disabled="opening"
        />
        <button
          id="refresh-labs"
          type="button"
          :disabled="loading || opening"
          @click="refresh"
        >
          刷新
        </button>
      </div>
      <p v-if="error" class="error-text" role="alert">{{ error }}</p>
      <div class="open-lab-list" :aria-busy="loading" aria-label="已保存实验">
        <p v-if="loading" class="open-lab-empty" role="status">
          正在读取实验列表…
        </p>
        <template v-else>
          <button
            v-for="item in matches"
            :key="item.id"
            type="button"
            class="open-lab-item"
            :class="{ selected: selected === item.id }"
            :data-lab-id="item.id"
            :aria-pressed="selected === item.id"
            :disabled="opening"
            @click="selected = item.id"
            @dblclick="openSelected(item.id)"
          >
            <span class="open-lab-symbol" aria-hidden="true">▤</span>
            <span class="open-lab-details"
              ><b>{{ item.name }}</b
              ><small>{{ item.id }} · {{ item.nodes }} 台设备</small></span
            >
            <span class="open-lab-state" :class="item.phase">{{
              labels[item.phase] || item.phase
            }}</span>
          </button>
          <p v-if="!matches.length" class="open-lab-empty">
            {{
              search.trim()
                ? "没有找到匹配的实验，试试其他关键词。"
                : "还没有保存的实验。关闭此窗口后新建实验，或从“实验”菜单导入拓扑 JSON。"
            }}
          </p>
        </template>
      </div>
      <div class="open-lab-footer">
        <span>{{ lab.labs.length }} 个已保存实验</span>
        <button type="button" :disabled="opening" @click="close">取消</button>
        <button
          id="confirm-open-lab"
          class="primary"
          type="submit"
          :disabled="!current || loading || opening || !!lab.operation"
        >
          {{ opening ? "正在打开…" : "打开实验" }}
        </button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
#open-lab-dialog {
  width: min(640px, calc(100vw - 48px));
  padding: 24px;
  border: 1px solid var(--border);
  border-radius: 14px;
}
.dialog-top {
  align-items: flex-start;
  margin-bottom: 20px;
  gap: 20px;
}
.dialog-top h2 {
  font-size: 19px;
}
.dialog-top > button {
  flex: none;
}
.open-lab-description {
  margin-top: 7px;
  line-height: 1.7;
  color: #6b778b;
  font-size: 12px;
}
.open-lab-search-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.open-lab-search-row input {
  flex: 1;
}
.open-lab-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 180px;
  max-height: min(420px, 48vh);
  overflow: auto;
  padding: 2px;
}
.open-lab-item {
  display: flex;
  gap: 12px;
  align-items: center;
  text-align: left;
  width: 100%;
  padding: 14px;
  min-height: 72px;
  border-radius: 9px;
}
.open-lab-item.selected {
  border-color: var(--blue);
  background: #eef4ff;
  box-shadow: 0 0 0 1px var(--blue);
}
.open-lab-symbol {
  font-size: 24px;
  color: #6d87a9;
  flex: none;
}
.open-lab-details {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.open-lab-details b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}
.open-lab-details small {
  color: #6b778b;
  overflow-wrap: anywhere;
}
.open-lab-state {
  font-size: 11px;
  border-radius: 20px;
  padding: 4px 9px;
  background: #f0f3f7;
  color: #607086;
  flex: none;
}
.open-lab-state.running {
  color: #1f7855;
  background: #e7f5ed;
}
.open-lab-state.error,
.open-lab-state.degraded {
  color: #9b6621;
  background: #fff3dd;
}
.open-lab-empty {
  padding: 50px 28px;
  line-height: 1.9;
  text-align: center;
  color: #6b778b;
}
.open-lab-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 18px;
  margin-top: 12px;
  border-top: 1px solid var(--border);
}
.open-lab-footer > span {
  flex: 1;
  color: #6b778b;
  font-size: 12px;
}
.open-lab-footer button {
  width: auto;
  margin: 0;
}
.error-text {
  margin-bottom: 12px;
}
</style>
