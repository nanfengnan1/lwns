<script setup lang="ts">
import { ref } from "vue";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import { parseTopology } from "../domain/topology";
import type { DeviceKind } from "../types/lab";
import DeviceIcon from "./DeviceIcon.vue";
import DeleteLabButton from "./DeleteLabButton.vue";

const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
const fileInput = ref<HTMLInputElement>();
function drag(event: DragEvent, kind: DeviceKind) {
  if (event.dataTransfer) {
    event.dataTransfer.setData("text/plain", kind);
    event.dataTransfer.effectAllowed = "copy";
  }
}
function loadExample() {
  if (editor.discardOK()) {
    lab.loadExample();
    ui.notify("示例已加载，尚未创建设备");
  }
}
async function selectLab(event: Event) {
  const input = event.target as HTMLSelectElement,
    id = input.value;
  input.value = lab.saved ? lab.topology.id : "";
  if (id && editor.discardOK()) await lab.load(id);
}
function exportTopology() {
  editor.commitDraft();
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(lab.topology, null, 2) + "\n"], {
      type: "application/json",
    }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = lab.topology.id + ".json";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  ui.notify("拓扑 JSON 已导出");
}
async function importTopology(event: Event) {
  const input = event.target as HTMLInputElement,
    file = input.files?.[0];
  input.value = "";
  if (!file || !editor.discardOK()) return;
  if (file.size > 1024 * 1024) throw Error("拓扑文件不能超过 1 MiB");
  const value = parseTopology(JSON.parse(await file.text()));
  lab.adopt(value);
  ui.notify("拓扑已导入，保存时将进行完整配置校验");
}
</script>

<template>
  <aside class="library">
    <div class="section-caption">WORKSPACE <span>01</span></div>
    <div class="library-lab-heading">
      <label class="small-label" for="lab-select">我的实验</label>
      <DeleteLabButton id="delete-current-lab">删除</DeleteLabButton>
    </div>
    <div class="select-row">
      <select
        id="lab-select"
        :value="lab.saved ? lab.topology.id : ''"
        :disabled="!!lab.operation"
        aria-label="选择实验"
        @change="ui.run(() => selectLab($event))"
      >
        <option v-if="!lab.saved" value="">
          {{ editor.unsaved ? "未保存的实验" : "空白画布" }}
        </option>
        <option v-for="item in lab.labs" :key="item.id" :value="item.id">
          {{ item.name }}
        </option>
      </select>
      <button
        id="new-lab"
        class="square"
        title="新建实验"
        aria-label="新建实验"
        :disabled="!!lab.operation"
        @click="editor.discardOK() && lab.newLab()"
      >
        ＋
      </button>
    </div>
    <div class="library-heading">
      <h2>设备库</h2>
      <span>拖入画布</span>
    </div>
    <div id="device-library">
      <button
        v-for="item in lab.catalog"
        :key="item.kind"
        class="device-card"
        :class="item.kind"
        :data-kind="item.kind"
        :draggable="!lab.locked"
        :disabled="lab.locked"
        @dragstart="drag($event, item.kind)"
        @click="ui.run(() => editor.addNode(item.kind))"
      >
        <span class="device-icon"><DeviceIcon :kind="item.kind" /></span>
        <span
          ><b>{{ item.title }}</b
          ><small>{{
            item.kind === "router"
              ? "FRRouting · L3"
              : item.kind === "switch"
                ? "Linux bridge · L2"
                : "Linux · 测试终端"
          }}</small></span
        ><span class="drag-dots">⠿</span>
      </button>
    </div>
    <div class="library-note">
      每台设备运行在独立容器中。<br />选择端口，用 veth 连接设备。
    </div>
    <div class="library-bottom">
      <button
        id="example"
        class="example-button"
        :disabled="!!lab.operation"
        @click="loadExample"
      >
        <span>⌘</span>
        <div><b>双网段路由实验</b><small>加载 5 台设备的示例拓扑</small></div>
        <span>↗</span>
      </button>
      <div class="file-buttons">
        <button
          id="import"
          :disabled="!!lab.operation"
          @click="fileInput?.click()"
        >
          导入 JSON</button
        ><button
          id="export"
          :disabled="!!lab.operation"
          @click="ui.run(exportTopology)"
        >
          导出 JSON
        </button>
      </div>
      <input
        id="import-file"
        ref="fileInput"
        type="file"
        accept="application/json,.json"
        hidden
        @change="ui.run(() => importTopology($event))"
      />
      <p>拓扑文件保留设备、端口与地址配置</p>
    </div>
  </aside>
</template>
