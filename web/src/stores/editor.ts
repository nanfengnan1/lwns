import { computed, reactive, ref, watch } from "vue";
import { defineStore } from "pinia";
import { assertConnection, clone, resizedPorts } from "../domain/topology";
import type {
  Annotation,
  Device,
  Endpoint,
  Point,
  Selection,
} from "../types/lab";
import { useLabStore } from "./lab";

export const useEditorStore = defineStore("editor", () => {
  const lab = useLabStore();
  const selected = ref<Selection>(null),
    pending = ref<Endpoint | null>(null);
  const mode = ref<"select" | "connect" | "annotation">("select");
  const view = reactive({ x: 0, y: 0, scale: 1 });
  const viewport = reactive({ width: 800, height: 500 });
  const fitRevision = ref(0);
  const draft = ref<Device | null>(null),
    draftDirty = ref(false);
  const annotationDraft = ref<Annotation | null>(null);
  const portCount = ref<number | string>(0),
    commandText = ref("");
  const node = computed(() =>
    selected.value?.type === "node"
      ? lab.getNode(selected.value.id)
      : undefined,
  );
  const link = computed(() =>
    selected.value?.type === "link"
      ? lab.topology.links.find((item) => item.id === selected.value?.id)
      : undefined,
  );
  const unsaved = computed(() => lab.dirty || draftDirty.value);
  const annotation = computed(() =>
    selected.value?.type === "annotation"
      ? lab.topology.annotations?.find((note) => note.id === selected.value?.id)
      : undefined,
  );
  const hint = computed(() =>
    pending.value
      ? `已选 ${lab.getNode(pending.value.node)?.name}.${pending.value.port}，点击另一台设备的空闲端口 · Esc 取消`
      : mode.value === "connect"
        ? "依次点击两台设备的空闲端口 · Esc 取消"
        : mode.value === "annotation"
          ? "点击画布放置注释 · Esc 取消"
          : "拖动设备或注释 · 顶部自动对齐 · 滚轮缩放",
  );

  function resetDraft() {
    draft.value = node.value ? clone(node.value) : null;
    annotationDraft.value = annotation.value ? clone(annotation.value) : null;
    portCount.value = node.value?.ports.length || 0;
    commandText.value = node.value?.command.length
      ? JSON.stringify(node.value.command)
      : "";
    draftDirty.value = false;
  }
  function touchDraft() {
    if (!lab.locked) draftDirty.value = true;
  }
  function commitDraft() {
    if (draftDirty.value && annotationDraft.value && annotation.value) {
      lab.updateAnnotation({
        ...annotationDraft.value,
        x: annotation.value.x,
        y: annotation.value.y,
      });
      resetDraft();
      return;
    }
    if (!draftDirty.value || !draft.value || !node.value) return;
    const next = clone(draft.value);
    // Canvas geometry can change while a properties draft is open.
    next.x = node.value.x;
    next.y = node.value.y;
    delete next.width;
    delete next.height;
    if (node.value.width !== undefined) next.width = node.value.width;
    if (node.value.height !== undefined) next.height = node.value.height;
    next.name = next.name.trim();
    next.image = next.image.trim();
    next.ports = resizedPorts(next, Number(portCount.value), lab.topology);
    try {
      next.command = commandText.value.trim()
        ? JSON.parse(commandText.value)
        : [];
    } catch {
      throw Error("启动命令必须是合法的 JSON 字符串数组");
    }
    lab.updateNode(next);
    resetDraft();
  }
  function select(value: Selection) {
    commitDraft();
    selected.value = value;
    resetDraft();
  }
  function setMode(value: "select" | "connect" | "annotation") {
    mode.value = value;
    pending.value = null;
  }
  function addNode(templateId: string, point?: Point) {
    commitDraft();
    const position = point || {
      x:
        (viewport.width / 2 - view.x) / view.scale +
        (lab.topology.nodes.length % 3) * 20,
      y: (viewport.height / 2 - view.y) / view.scale,
    };
    const added = lab.addNode(templateId, position);
    selected.value = { type: "node", id: added.id };
    resetDraft();
  }
  function choosePort(end: Endpoint): boolean {
    lab.assertEditable();
    commitDraft();
    assertConnection(lab.topology, end);
    if (!pending.value) {
      select({ type: "node", id: end.node });
      pending.value = end;
      return false;
    }
    lab.connect(pending.value, end);
    pending.value = null;
    return true;
  }
  function addAnnotation(point: Point) {
    commitDraft();
    const note = lab.addAnnotation(point);
    selected.value = { type: "annotation", id: note.id };
    setMode("select");
    resetDraft();
  }
  function deleteSelection() {
    if (!selected.value || lab.locked) return;
    lab.remove(selected.value.type, selected.value.id);
    selected.value = null;
    pending.value = null;
    resetDraft();
  }
  function discardOK() {
    return (
      !unsaved.value || window.confirm("当前有未保存的修改，是否放弃这些修改？")
    );
  }
  watch(
    () => lab.documentVersion,
    () => {
      selected.value = null;
      pending.value = null;
      mode.value = "select";
      resetDraft();
      fitRevision.value++;
    },
    { flush: "sync" },
  );
  watch(node, () => {
    if (!draftDirty.value) resetDraft();
  });
  watch(annotation, () => {
    if (!draftDirty.value) resetDraft();
  });
  watch(
    () => node.value?.config,
    () => {
      if (!draftDirty.value) resetDraft();
    },
  );
  return {
    selected,
    pending,
    mode,
    view,
    viewport,
    fitRevision,
    draft,
    annotation,
    annotationDraft,
    draftDirty,
    portCount,
    commandText,
    node,
    link,
    unsaved,
    hint,
    touchDraft,
    commitDraft,
    select,
    setMode,
    addNode,
    addAnnotation,
    choosePort,
    deleteSelection,
    discardOK,
  };
});
