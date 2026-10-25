import { defineStore } from "pinia";
import { ref, watch } from "vue";
import { useLabStore } from "./lab";
import { useUiStore } from "./ui";

export interface TerminalTab {
  id: string;
  lab: string;
  node: string;
  name: string;
  deployment: string;
  mode: "default" | "shell";
  state: "connecting" | "connected" | "disconnected";
}

export const useTerminalsStore = defineStore("terminals", () => {
  const lab = useLabStore(),
    ui = useUiStore();
  const tabs = ref<TerminalTab[]>([]);
  const active = ref("");
  function open(nodeId: string, mode: "default" | "shell" = "default") {
    const node = lab.getRuntimeNode(nodeId),
      deployment = lab.runtime?.deployment;
    if (!node || !deployment || !lab.canOpenTerminal(nodeId))
      throw Error("请先部署设备，运行就绪后再打开终端");
    if (
      (lab.getTemplate(node)?.console ||
        (node.kind === "router" ? "vtysh" : "sh")) === "sh"
    )
      mode = "shell";
    const id = `${lab.topology.id}:${deployment}:${nodeId}:${mode}`;
    if (!tabs.value.some((tab) => tab.id === id)) {
      if (tabs.value.length >= 12)
        throw Error("最多打开 12 个终端标签，请先关闭不用的标签");
      tabs.value.push({
        id,
        lab: lab.topology.id,
        node: nodeId,
        name: node.name,
        deployment,
        mode,
        state: "connecting",
      });
    }
    active.value = id;
    ui.showPanel("console");
  }
  function close(id: string) {
    const index = tabs.value.findIndex((tab) => tab.id === id);
    if (index < 0) return;
    tabs.value.splice(index, 1);
    if (active.value === id)
      active.value =
        tabs.value[Math.min(index, tabs.value.length - 1)]?.id || "";
  }
  watch(
    () => [lab.documentVersion, lab.terminalRevision],
    () => {
      tabs.value = [];
      active.value = "";
    },
  );
  watch(
    () => [
      lab.runtime?.deployment,
      lab.phase,
      Object.keys(lab.runtime?.nodes || {}).join(","),
    ],
    () => {
      for (const tab of [...tabs.value]) {
        if (
          tab.deployment !== lab.runtime?.deployment ||
          !lab.runtime?.nodes[tab.node] ||
          ["destroying", "updating"].includes(lab.phase)
        )
          close(tab.id);
      }
    },
  );
  return { tabs, active, open, close };
});
