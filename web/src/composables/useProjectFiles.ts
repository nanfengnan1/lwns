import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import { parseTopology } from "../domain/topology";

/** Shared by the experiment menu and the toolbar; JSON is a topology export. */
export function useProjectFiles() {
  const lab = useLabStore(),
    editor = useEditorStore(),
    ui = useUiStore();

  async function save() {
    editor.commitDraft();
    await lab.save();
    ui.notify(
      lab.runtime?.deployment ? "实验布局已保存" : "实验已保存到当前宿主机",
    );
  }

  async function applyTopology() {
    editor.commitDraft();
    if (!lab.pendingUpdate) {
      ui.notify("没有需要应用的设备或连线修改，可点击保存布局");
      return;
    }
    if (!lab.canUpdate)
      throw Error("请等待设备运行就绪；应用失败后请先清理再部署");
    const { added, removed, rebuilt } = lab.updateChanges;
    const affected = [...removed, ...rebuilt].map((node) => node.name);
    const message = [
      `应用当前拓扑到运行设备？新增 ${added.length} 台，删除 ${removed.length} 台，重建 ${rebuilt.length} 台。`,
      ...(affected.length
        ? [
            `删除或重建设备：${affected.join("、")}。`,
            "这些设备未保存的终端配置可能丢失，建议先保存设备配置。",
          ]
        : []),
      "变更会同步到容器和网线，本实验的现有终端与抓包会断开。",
    ].join("\n");
    if (!window.confirm(message)) return;
    await lab.startJob("update");
    editor.pending = null;
    ui.showPanel("logs");
    ui.notify("正在应用拓扑，请查看部署日志");
  }

  async function importFile(file: Pick<File, "size" | "text">) {
    if (lab.operation) throw Error("请等待当前操作完成后再打开拓扑文件");
    if (file.size > 1024 * 1024) throw Error("拓扑文件不能超过 1 MiB");
    const version = lab.documentVersion;
    const topology = parseTopology(JSON.parse(await file.text()));
    if (lab.operation || version !== lab.documentVersion)
      throw Error("当前实验已变化，请重新选择要打开的文件");
    if (!editor.discardOK()) return;
    lab.adopt(topology);
    ui.notify("拓扑 JSON 已导入，保存实验后写入当前宿主机");
  }

  function exportFile() {
    if (lab.operation) throw Error("请等待当前操作完成后再导出拓扑");
    editor.commitDraft();
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(lab.topology, null, 2) + "\n"], {
        type: "application/json",
      }),
    );
    try {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = lab.topology.id + ".json";
      anchor.click();
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    ui.notify("拓扑 JSON 已导出；设备共享目录与镜像不包含在文件中");
  }

  return { save, applyTopology, importFile, exportFile };
}
