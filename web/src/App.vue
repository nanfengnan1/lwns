<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { getToken, setToken } from "./api/client";
import { useLabStore } from "./stores/lab";
import { useEditorStore } from "./stores/editor";
import { useUiStore } from "./stores/ui";
import DeviceLibrary from "./components/DeviceLibrary.vue";
import LabToolbar from "./components/LabToolbar.vue";
import TopologyCanvas from "./components/TopologyCanvas.vue";
import DeviceInspector from "./components/DeviceInspector.vue";
import WorkbenchPanels from "./components/WorkbenchPanels.vue";
import WorkbenchDialogs from "./components/WorkbenchDialogs.vue";
import polarBear from "./assets/polar-bear.svg";

const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
let poll: ReturnType<typeof setInterval> | undefined;
function keydown(event: KeyboardEvent) {
  if (
    (event.target as Element).closest(
      "input,textarea,select,dialog,.device-terminal,#console",
    ) ||
    ui.accessOpen ||
    ui.infoOpen
  )
    return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key === "Escape") editor.setMode("select");
  else if (event.key === "Delete" || event.key === "Backspace") {
    event.preventDefault();
    editor.deleteSelection();
  } else if (event.key.toLowerCase() === "c" && !lab.locked)
    editor.setMode("connect");
  else if (event.key.toLowerCase() === "v") editor.setMode("select");
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (editor.unsaved) {
    event.preventDefault();
    event.returnValue = "";
  }
}
onMounted(async () => {
  const url = new URL(location.href),
    fromURL = new URLSearchParams(url.hash.slice(1)).get("token");
  setToken(fromURL || sessionStorage.getItem("route-ovs-token") || "");
  if (fromURL) {
    url.hash = "";
    history.replaceState(null, "", url);
    sessionStorage.setItem("route-ovs-token", getToken());
  }
  document.addEventListener("keydown", keydown);
  window.addEventListener("beforeunload", beforeUnload);
  poll = setInterval(() => {
    if (lab.saved && (lab.runtime?.deployment || lab.busy) && !ui.accessOpen)
      void ui.run(lab.refresh);
  }, 4000);
  if (getToken()) {
    try {
      await lab.bootstrap();
    } catch (error) {
      ui.report(error);
      ui.accessOpen = true;
    }
  } else ui.accessOpen = true;
});
onBeforeUnmount(() => {
  clearInterval(poll);
  document.removeEventListener("keydown", keydown);
  window.removeEventListener("beforeunload", beforeUnload);
});
</script>

<template>
  <header class="topbar">
    <a class="brand" href="/" aria-label="Route OVS 工作台"
      ><img
        class="brand-mark"
        :src="polarBear"
        alt="北极熊头像"
        width="36"
        height="36"
      />
      <b>route<span>ovs</span></b
      ><span class="brand-divider"></span
      ><span class="brand-caption">网络实验室</span></a
    >
    <div class="top-actions">
      <span class="mode-pill">DOCKER / VETH</span
      ><button id="environment" class="quiet" @click="ui.infoOpen = true">
        <i
          class="status-dot"
          :class="{
            ready: lab.environment.ready,
            warn: !lab.environment.ready,
          }"
        ></i
        ><span>{{
          lab.environment.ready
            ? "Linux 主机已连接"
            : lab.environment.preview
              ? "设计模式"
              : "部署环境未就绪"
        }}</span>
      </button>
    </div>
  </header>
  <main class="workspace">
    <DeviceLibrary />
    <section class="stage">
      <LabToolbar /><TopologyCanvas /><WorkbenchPanels />
    </section>
    <DeviceInspector />
  </main>
  <WorkbenchDialogs />
</template>
