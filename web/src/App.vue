<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref } from "vue";
import { useRetainedPanel } from "./composables/useRetainedPanel";
import { useLayoutStore } from "./stores/layout";
import SidebarPanel from "./components/SidebarPanel.vue";
import ProjectNameDialog from "./components/ProjectNameDialog.vue";
import LabOpenDialog from "./components/LabOpenDialog.vue";
import WorkbenchMenu from "./components/WorkbenchMenu.vue";
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
import steppeWolf from "./assets/steppe-wolf.svg";

const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
const ImageManager = defineAsyncComponent(
  () => import("./components/ImageManager.vue"),
);
const DevicePackageManager = defineAsyncComponent(
  () => import("./components/DevicePackageManager.vue"),
);
const CaptureManager = defineAsyncComponent(
  () => import("./components/CaptureManager.vue"),
);
const imagesLoaded = useRetainedPanel(() => ui.imagesOpen);
const devicesLoaded = useRetainedPanel(() => ui.devicesOpen);
const capturesLoaded = useRetainedPanel(() => ui.captureOpen);
let poll: ReturnType<typeof setInterval> | undefined;
const layout = useLayoutStore();
const workspace = ref<HTMLElement>();
let layoutObserver: ResizeObserver | undefined;
function keydown(event: KeyboardEvent) {
  if (
    (event.target as Element).closest(
      "input,textarea,select,dialog,.device-terminal,#console,.workbench-menu",
    ) ||
    ui.accessOpen ||
    ui.infoOpen ||
    ui.imagesOpen ||
    ui.devicesOpen ||
    ui.captureOpen ||
    ui.labDialogMode ||
    ui.labOpen ||
    ui.menuOpen
  )
    return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key === "Escape") editor.setMode("select");
  else if (event.key === "Delete" || event.key === "Backspace") {
    event.preventDefault();
    editor.deleteSelection();
  } else if (event.key.toLowerCase() === "c" && !lab.locked)
    editor.setMode("connect");
  else if (event.key.toLowerCase() === "t" && !lab.locked)
    editor.setMode("annotation");
  else if (event.key.toLowerCase() === "v") editor.setMode("select");
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (editor.unsaved) {
    event.preventDefault();
    event.returnValue = "";
  }
}
function chunkLoadFailed() {
  // Do not reload automatically: the canvas may contain unsaved work.
  ui.report(
    new Error(
      "功能模块加载失败，请检查网络；若服务刚更新，请先导出未保存的拓扑，再刷新页面。",
    ),
  );
}
onMounted(async () => {
  layout.restore();
  layoutObserver = new ResizeObserver(() => {
    if (workspace.value) layout.workspaceWidth = workspace.value.clientWidth;
  });
  if (workspace.value) {
    layout.workspaceWidth = workspace.value.clientWidth;
    layoutObserver.observe(workspace.value);
  }
  const url = new URL(location.href),
    fromURL = new URLSearchParams(url.hash.slice(1)).get("token");
  setToken(
    fromURL ||
      sessionStorage.getItem("lwns-token") ||
      sessionStorage.getItem("route-ovs-token") ||
      "",
  );
  if (fromURL) {
    url.hash = "";
    history.replaceState(null, "", url);
    sessionStorage.setItem("lwns-token", getToken());
  }
  document.addEventListener("keydown", keydown);
  window.addEventListener("beforeunload", beforeUnload);
  window.addEventListener("vite:preloadError", chunkLoadFailed);
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
  layoutObserver?.disconnect();
  clearInterval(poll);
  document.removeEventListener("keydown", keydown);
  window.removeEventListener("beforeunload", beforeUnload);
  window.removeEventListener("vite:preloadError", chunkLoadFailed);
});
</script>

<template>
  <header class="topbar">
    <a
      class="brand"
      href="/"
      aria-label="lwns · Linux Web Network Simulator"
      title="Linux Web Network Simulator"
      ><img
        class="brand-mark"
        :src="steppeWolf"
        alt="草原狼头像"
        width="36"
        height="36"
      />
      <b>lw<span>ns</span></b
      ><span class="brand-divider"></span
      ><span class="brand-caption">网络实验室</span></a
    >
    <WorkbenchMenu />
    <div class="top-actions">
      <span
        id="server-host"
        class="mode-pill"
        :title="`当前服务器：${lab.serverHost}`"
        >{{ lab.serverHost }}</span
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
  <main
    ref="workspace"
    class="workspace"
    :style="{
      gridTemplateColumns: `${layout.widths.left}px minmax(460px, 1fr) ${layout.widths.right}px`,
    }"
  >
    <SidebarPanel side="left" title="设备库"><DeviceLibrary /></SidebarPanel>
    <section class="stage">
      <LabToolbar /><TopologyCanvas /><WorkbenchPanels />
    </section>
    <SidebarPanel side="right" title="属性栏"><DeviceInspector /></SidebarPanel>
  </main>
  <WorkbenchDialogs />
  <ProjectNameDialog />
  <LabOpenDialog />
  <ImageManager v-if="imagesLoaded" />
  <DevicePackageManager v-if="devicesLoaded" />
  <CaptureManager v-if="capturesLoaded" />
</template>
