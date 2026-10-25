import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { api } from "../api/client";
import {
  assertConnection,
  clone,
  connection,
  parseTopology,
  projectName,
  parseAnnotation,
  uniqueId,
} from "../domain/topology";
import type {
  Annotation,
  Bootstrap,
  Device,
  ConfigSaveResult,
  DeviceConfigStatus,
  DeviceTemplate,
  Endpoint,
  Environment,
  LabRecord,
  LabSummary,
  Point,
  ProjectSaveResult,
  Runtime,
  Topology,
} from "../types/lab";
import { alignDevices } from "../domain/canvas";
import { deploymentChanges, networkSignature } from "../domain/deployment";

function emptyTopology(): Topology {
  return {
    version: 1,
    id: uniqueId("lab-"),
    name: "空白画布",
    nodes: [],
    links: [],
  };
}

export const useLabStore = defineStore("lab", () => {
  const topology = ref<Topology>(emptyTopology());
  const savedTopology = ref<Topology>(clone(topology.value));
  const terminalRevision = ref(0);
  const runtime = ref<Runtime | null>(null);
  const configs = ref<Record<string, DeviceConfigStatus>>({});
  const catalog = ref<DeviceTemplate[]>([]),
    labs = ref<LabSummary[]>([]);
  const environment = ref<Environment>({
    ready: false,
    preview: false,
    errors: [],
    images: [],
  });
  const saved = ref(false),
    dirty = ref(false),
    busy = ref(false);
  const saveWarning = ref("");
  const operation = ref(""),
    documentVersion = ref(0);
  const serverHost = computed(
    () =>
      (typeof window !== "undefined" && window.location?.host) || "当前服务器",
  );
  const phase = computed(() => runtime.value?.phase || "idle");
  const layoutLocked = computed(
    () =>
      busy.value ||
      !!operation.value ||
      ["deploying", "updating", "destroying"].includes(phase.value),
  );
  const locked = computed(() => layoutLocked.value);
  const pendingUpdate = computed(
    () =>
      !!runtime.value?.deployment &&
      networkSignature(topology.value) !==
        networkSignature(savedTopology.value),
  );
  const updateChanges = computed(() =>
    deploymentChanges(savedTopology.value, topology.value),
  );
  const runningNodes = computed(() =>
    savedTopology.value.nodes.filter(
      (node) => !!runtime.value?.deployment && !!runtime.value.nodes[node.id],
    ),
  );
  const canUpdate = computed(
    () =>
      saved.value &&
      !!runtime.value?.deployment &&
      phase.value === "running" &&
      !layoutLocked.value &&
      environment.value.ready,
  );
  const canRename = computed(
    () =>
      !busy.value &&
      !operation.value &&
      !["deploying", "updating", "destroying"].includes(phase.value),
  );
  const images = computed(() => [
    ...new Set([
      ...environment.value.images,
      ...catalog.value.map((item) => item.image),
    ]),
  ]);
  const canDeploy = computed(
    () =>
      !locked.value &&
      !runtime.value?.deployment &&
      environment.value.ready &&
      topology.value.nodes.length > 0,
  );
  const canDestroy = computed(
    () =>
      saved.value &&
      !!runtime.value?.deployment &&
      environment.value.ready &&
      !layoutLocked.value,
  );
  const canClose = computed(
    () => !layoutLocked.value && (saved.value || dirty.value),
  );
  let refreshing = false;
  let runtimeRevision = 0;
  let catalogRevision = 0;
  let updateTarget: Topology | null = null;

  function assertEditable() {
    if (locked.value) throw Error("请等待当前操作完成后再编辑拓扑");
  }
  function assertLayoutEditable() {
    if (layoutLocked.value) throw Error("请等待当前操作完成后再调整布局");
  }
  function getNode(id: string) {
    return topology.value.nodes.find((node) => node.id === id);
  }
  function getRuntimeNode(id: string) {
    return runningNodes.value.find((node) => node.id === id);
  }
  function canOpenTerminal(id: string) {
    return (
      !!getRuntimeNode(id) && environment.value.ready && !layoutLocked.value
    );
  }
  function canCapture(linkId: string) {
    const link = topology.value.links.find((item) => item.id === linkId);
    const running = savedTopology.value.links.find(
      (item) => item.id === linkId,
    );
    return !!(
      saved.value &&
      !layoutLocked.value &&
      environment.value.ready &&
      link &&
      running &&
      link.a.node === running.a.node &&
      link.a.port === running.a.port &&
      link.b.node === running.b.node &&
      link.b.port === running.b.port &&
      getRuntimeNode(link.a.node) &&
      getRuntimeNode(link.b.node)
    );
  }
  function getTemplate(node: Device) {
    const matches = catalog.value.filter((item) =>
      node.template
        ? (item.template_id || item.id) === node.template
        : item.kind === node.kind,
    );
    return matches.find((item) => item.image === node.image) || matches[0];
  }
  function supportsConfig(node: Device) {
    return (
      getTemplate(node)?.capabilities?.save_config ??
      (node.template === "frr" || (!node.template && node.kind === "router"))
    );
  }
  function canSaveConfig(nodeId?: string) {
    return (
      saved.value &&
      !!runtime.value?.deployment &&
      environment.value.ready &&
      !busy.value &&
      !operation.value &&
      !["deploying", "updating", "destroying"].includes(phase.value) &&
      runningNodes.value.some(
        (node) =>
          (!nodeId || node.id === nodeId) &&
          supportsConfig(node) &&
          runtime.value?.nodes[node.id],
      )
    );
  }
  async function loadConfig(nodeId: string) {
    if (
      !saved.value ||
      layoutLocked.value ||
      !savedTopology.value.nodes.some((node) => node.id === nodeId)
    )
      return;
    const version = documentVersion.value,
      revision = runtimeRevision;
    const result = await api<Record<string, DeviceConfigStatus>>(
      `/api/labs/${topology.value.id}/configs/${nodeId}`,
    );
    if (
      version === documentVersion.value &&
      revision === runtimeRevision &&
      !operation.value
    )
      Object.assign(configs.value, result);
  }
  async function saveConfigs(nodeId?: string) {
    if (!canSaveConfig(nodeId))
      throw Error("请先部署支持保存配置的设备，等待操作完成");
    operation.value = "save-config";
    runtimeRevision++;
    try {
      const result = await api<ConfigSaveResult>(
        `/api/labs/${topology.value.id}/configs`,
        "POST",
        nodeId ? { node: nodeId } : {},
      );
      runtime.value = result.runtime;
      for (const item of result.results) {
        if (!item.ok) continue;
        if (item.status) configs.value[item.node] = item.status;
        const node = getNode(item.node);
        const original = savedTopology.value.nodes.find(
          (node) => node.id === item.node,
        );
        if (original && item.config !== undefined) {
          // Preserve an explicitly edited startup config in the local draft.
          if (node && node.config === original.config)
            node.config = item.config;
          original.config = item.config;
        }
      }
      const failures = result.results.filter((item) => !item.ok);
      if (failures.length)
        throw Error(
          `部分配置未保存：${failures.map((item) => `${getNode(item.node)?.name || item.node}：${item.error}`).join("；")}`,
        );
      return result.results;
    } finally {
      operation.value = "";
    }
  }
  function getConnection(node: string, port: string) {
    return connection(topology.value, node, port);
  }
  function peerLabel(node: string, port: string) {
    const link = getConnection(node, port);
    if (!link) return "空闲端口";
    const peer = link.a.node === node && link.a.port === port ? link.b : link.a;
    return `${getNode(peer.node)?.name || peer.node}.${peer.port}`;
  }
  function adopt(value: Topology, record?: LabRecord) {
    topology.value = parseTopology(value);
    savedTopology.value = parseTopology(record?.topology || topology.value);
    updateTarget = null;
    saveWarning.value = "";
    configs.value = {};
    runtimeRevision++;
    runtime.value = record?.runtime ?? null;
    saved.value = !!record;
    dirty.value = !record;
    busy.value = !!record?.busy;
    documentVersion.value++;
  }
  async function bootstrap() {
    if (operation.value) return;
    operation.value = "load";
    try {
      const data = await api<Bootstrap>("/api/bootstrap");
      catalog.value = data.catalog;
      environment.value = data.environment;
      labs.value = data.labs;
      // Loading the workbench only refreshes its catalog and experiment list.
      // Opening a project is explicit; re-authentication must preserve drafts.
    } finally {
      operation.value = "";
    }
  }
  async function load(id: string) {
    if (layoutLocked.value) throw Error("请等待当前操作完成后再打开项目");
    const version = documentVersion.value;
    operation.value = "load";
    try {
      const record = await api<LabRecord>(`/api/labs/${id}/open`, "POST", {});
      if (version !== documentVersion.value)
        throw Error("当前项目已变化，请重新打开项目");
      adopt(record.topology, record);
    } finally {
      operation.value = "";
    }
  }
  async function createProject(value: string) {
    if (layoutLocked.value) throw Error("请等待当前操作完成后再新建项目");
    const name = projectName(value),
      version = documentVersion.value;
    operation.value = "create";
    try {
      const record = await api<LabRecord>("/api/labs", "POST", { name });
      const summary: LabSummary = {
        id: record.topology.id,
        name: record.topology.name,
        nodes: record.topology.nodes.length,
        phase: record.runtime.phase,
      };
      labs.value = [
        summary,
        ...labs.value.filter((item) => item.id !== summary.id),
      ];
      if (version !== documentVersion.value)
        throw Error("项目已在服务器创建，当前画布已变化，请从打开项目中选择");
      adopt(record.topology, record);
    } finally {
      operation.value = "";
    }
  }
  async function closeProject() {
    if (layoutLocked.value) throw Error("请等待当前操作完成后再关闭项目");
    const version = documentVersion.value;
    operation.value = "close";
    try {
      if (saved.value)
        await api(`/api/labs/${topology.value.id}/close`, "POST", {});
      if (version !== documentVersion.value)
        throw Error("当前项目已变化，请重新关闭项目");
      adopt(emptyTopology());
      dirty.value = false;
    } finally {
      operation.value = "";
    }
  }
  // Internal draft helper, also used by JSON/import state tests. The New Project
  // dialog uses createProject so a successful UI create always exists remotely.
  function newLab(name = "未命名实验") {
    if (operation.value) return;
    adopt({
      version: 1,
      id: uniqueId("lab-"),
      name: projectName(name),
      nodes: [],
      links: [],
    });
  }
  async function rename(value: string) {
    if (!canRename.value) throw Error("请等待当前操作完成后再重命名项目");
    const name = projectName(value);
    if (name === topology.value.name) return;
    if (!saved.value) {
      topology.value.name = name;
      dirty.value = true;
      return;
    }
    const id = topology.value.id,
      version = documentVersion.value;
    operation.value = "rename";
    runtimeRevision++;
    try {
      const result = await api<{ id: string; name: string }>(
        `/api/labs/${id}/rename`,
        "POST",
        { name },
      );
      const item = labs.value.find((entry) => entry.id === id);
      if (item) item.name = result.name;
      if (version === documentVersion.value) {
        topology.value.name = result.name;
        savedTopology.value.name = result.name;
      }
      // Other unsaved topology edits and inspector drafts remain unsaved.
    } finally {
      operation.value = "";
    }
  }
  function addNode(templateId: string, point: Point) {
    assertEditable();
    if (topology.value.nodes.length >= 64) throw Error("最多支持 64 台设备");
    const template = catalog.value.find(
      (item) => item.id === templateId || item.kind === templateId,
    );
    if (!template) throw Error("未知设备类型");
    const kind = template.kind;
    const prefix = { router: "r", switch: "sw", host: "pc", firewall: "fw" }[
      kind
    ];
    let i = 1;
    while (getNode(prefix + i) || getRuntimeNode(prefix + i)) i++;
    let number = 1;
    while (
      topology.value.nodes.some((n) => n.name === template.prefix + number)
    )
      number++;
    const node: Device = {
      id: prefix + i,
      name: template.prefix + number,
      kind,
      ...(template.id ? { template: template.template_id || template.id } : {}),
      image: template.image,
      x: Math.round(point.x / 12) * 12,
      y: Math.round(point.y / 12) * 12,
      ports: Array.from({ length: template.ports }, (_, n) => ({
        name: `eth${n}`,
        address: "",
      })),
      gateway: "",
      command: [],
      config: "",
    };
    topology.value.nodes.push(node);
    dirty.value = true;
    return node;
  }
  function updateNode(value: Device) {
    assertEditable();
    const next = clone(topology.value),
      index = next.nodes.findIndex((node) => node.id === value.id);
    if (index < 0) throw Error("设备不存在");
    next.nodes[index] = clone(value);
    topology.value = parseTopology(next);
    dirty.value = true;
  }
  function moveNode(id: string, point: Point) {
    assertLayoutEditable();
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y))
      throw Error("布局坐标无效");
    const node = getNode(id);
    if (node) {
      node.x = Math.max(-100000, Math.min(100000, point.x));
      node.y = Math.max(-100000, Math.min(100000, point.y));
      dirty.value = true;
    }
  }
  function connect(a: Endpoint, b: Endpoint) {
    assertEditable();
    assertConnection(topology.value, a, b);
    topology.value.links.push({ id: uniqueId("l"), a: { ...a }, b: { ...b } });
    dirty.value = true;
  }
  function autoAlign() {
    assertLayoutEditable();
    const positions = alignDevices(topology.value);
    let moved = 0;
    for (const node of topology.value.nodes) {
      const point = positions[node.id];
      if (node.x !== point.x || node.y !== point.y) {
        Object.assign(node, point);
        moved++;
      }
    }
    if (moved) dirty.value = true;
    return moved;
  }
  function setLinkOptimization(enabled: boolean) {
    assertLayoutEditable();
    topology.value.optimizeLinks = enabled;
    dirty.value = true;
  }
  function addAnnotation(point: Point) {
    assertEditable();
    if ((topology.value.annotations?.length || 0) >= 100)
      throw Error("最多支持 100 条注释");
    const note = parseAnnotation({
      id: uniqueId("note-"),
      ...point,
      text: "网段：192.168.1.0/24",
      color: "#66521c",
      background: "#fff7d6",
      fontSize: 16,
    });
    (topology.value.annotations ??= []).push(note);
    dirty.value = true;
    return note;
  }
  function updateAnnotation(value: Annotation) {
    assertEditable();
    const note = parseAnnotation(value);
    const index =
      topology.value.annotations?.findIndex((item) => item.id === note.id) ??
      -1;
    if (index < 0) throw Error("注释不存在");
    topology.value.annotations![index] = note;
    dirty.value = true;
  }
  function moveAnnotation(id: string, point: Point) {
    assertLayoutEditable();
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y))
      throw Error("布局坐标无效");
    const note = topology.value.annotations?.find((item) => item.id === id);
    if (note) {
      note.x = Math.max(-100000, Math.min(100000, point.x));
      note.y = Math.max(-100000, Math.min(100000, point.y));
      dirty.value = true;
    }
  }
  function remove(type: "node" | "link" | "annotation", id: string) {
    assertEditable();
    if (type === "node") {
      topology.value.nodes = topology.value.nodes.filter((n) => n.id !== id);
      topology.value.links = topology.value.links.filter(
        (link) => link.a.node !== id && link.b.node !== id,
      );
    } else if (type === "annotation") {
      topology.value.annotations = topology.value.annotations?.filter(
        (note) => note.id !== id,
      );
    } else
      topology.value.links = topology.value.links.filter(
        (link) => link.id !== id,
      );
    dirty.value = true;
  }
  async function save() {
    assertEditable();
    if (pendingUpdate.value)
      throw Error(
        "拓扑包含未应用的设备或连线修改，请点击“应用拓扑”；保存布局不会修改运行设备",
      );
    const payload = parseTopology(topology.value),
      deployed = !!runtime.value?.deployment;
    runtimeRevision++;
    operation.value = "save";
    try {
      const record = await api<LabRecord>(
        `/api/labs/${payload.id}`,
        "PUT",
        payload,
      );
      const normalized = parseTopology(record.topology);
      savedTopology.value = clone(normalized);
      topology.value = normalized;
      if (!deployed) {
        runtime.value = record.runtime;
      }
      saved.value = true;
      dirty.value = false;
      if (!deployed) labs.value = await api<LabSummary[]>("/api/labs");
    } finally {
      operation.value = "";
    }
  }
  async function saveProject() {
    assertEditable();
    if (pendingUpdate.value)
      throw Error("拓扑包含未应用的设备或连线修改，请先点击“应用拓扑”");
    const payload = parseTopology(topology.value),
      version = documentVersion.value;
    operation.value = "save";
    runtimeRevision++;
    try {
      const result = await api<ProjectSaveResult>(
        `/api/labs/${payload.id}/save`,
        "POST",
        { topology: payload },
      );
      if (version !== documentVersion.value)
        throw Error(
          "服务器已完成保存，当前画布已变化，请重新打开原项目检查结果",
        );
      // A project save updates the document in place: terminal tabs, selection,
      // and their document identity must survive saving device configuration.
      const normalized = parseTopology(result.record.topology);
      savedTopology.value = clone(normalized);
      topology.value = normalized;
      runtime.value = result.record.runtime;
      busy.value = !!result.record.busy;
      saved.value = true;
      dirty.value = false;
      for (const item of result.results)
        if (item.ok && item.status) configs.value[item.node] = item.status;
      saveWarning.value = result.results.some(
        (item) => !item.ok && !item.skipped,
      )
        ? "部分设备配置未保存"
        : result.results.some((item) => item.skipped)
          ? "部分设备仅保存拓扑"
          : "";
      const summary: LabSummary = {
        id: normalized.id,
        name: normalized.name,
        nodes: normalized.nodes.length,
        phase: result.record.runtime.phase,
      };
      labs.value = [
        summary,
        ...labs.value.filter((item) => item.id !== summary.id),
      ];
      return result;
    } finally {
      operation.value = "";
    }
  }
  async function startJob(action: "deploy" | "destroy" | "update") {
    const allowed =
      action === "deploy"
        ? canDeploy.value
        : action === "update"
          ? canUpdate.value && pendingUpdate.value
          : canDestroy.value;
    if (!allowed) throw Error("当前状态不允许执行此操作");
    if (action === "deploy" && (!saved.value || dirty.value)) await save();
    const target = action === "update" ? parseTopology(topology.value) : null;
    runtimeRevision++;
    operation.value = action;
    try {
      const record = await api<LabRecord>(
        `/api/labs/${topology.value.id}/${action}`,
        "POST",
        target ? { topology: target, base: clone(savedTopology.value) } : {},
      );
      runtime.value = record.runtime;
      busy.value = true;
      if (target) {
        updateTarget = target;
        terminalRevision.value++;
      }
    } finally {
      operation.value = "";
    }
  }
  async function refresh() {
    if (!saved.value || refreshing || operation.value) return;
    refreshing = true;
    const version = documentVersion.value,
      revision = runtimeRevision,
      id = topology.value.id;
    try {
      const record = await api<LabRecord>(`/api/labs/${id}`);
      if (
        version !== documentVersion.value ||
        revision !== runtimeRevision ||
        operation.value
      )
        return;
      const wasBusy = layoutLocked.value;
      runtime.value = record.runtime;
      busy.value = !!record.busy;
      if (updateTarget && !record.busy && record.runtime.phase !== "updating") {
        if (
          record.runtime.phase !== "error" &&
          record.runtime.phase !== "degraded" &&
          networkSignature(record.topology) === networkSignature(updateTarget)
        ) {
          const normalized = parseTopology(record.topology);
          topology.value = normalized;
          savedTopology.value = clone(normalized);
          configs.value = {};
          dirty.value = false;
        }
        // An error retains the editable local draft for export, cleanup and redeploy.
        updateTarget = null;
      } else if (wasBusy && !dirty.value && !updateTarget && !record.busy) {
        const normalized = parseTopology(record.topology);
        savedTopology.value = clone(normalized);
        if (JSON.stringify(topology.value) !== JSON.stringify(normalized))
          topology.value = normalized;
      }
    } finally {
      refreshing = false;
    }
  }
  async function refreshEnvironment() {
    environment.value = await api<Environment>("/api/environment");
    await refresh();
  }
  async function refreshCatalog() {
    const revision = ++catalogRevision;
    const result = await api<DeviceTemplate[]>("/api/catalog");
    if (revision === catalogRevision) catalog.value = result;
  }
  async function deleteLab() {
    assertEditable();
    if (runtime.value?.deployment) throw Error("请先清理设备，再删除实验");
    runtimeRevision++;
    operation.value = "delete";
    try {
      // An imported draft may share an ID with a saved lab. Only delete a
      // server record when the current document was actually saved or loaded.
      if (saved.value) {
        const id = topology.value.id;
        await api(`/api/labs/${id}`, "DELETE");
        labs.value = labs.value.filter((item) => item.id !== id);
      }
      adopt(emptyTopology());
      dirty.value = false;
    } finally {
      operation.value = "";
    }
  }
  return {
    topology,
    runtime,
    configs,
    catalog,
    labs,
    environment,
    saved,
    saveWarning,
    dirty,
    busy,
    operation,
    serverHost,
    documentVersion,
    terminalRevision,
    pendingUpdate,
    updateChanges,
    runningNodes,
    canUpdate,
    locked,
    layoutLocked,
    phase,
    images,
    canDeploy,
    canRename,
    canDestroy,
    canClose,
    assertEditable,
    assertLayoutEditable,
    getNode,
    getRuntimeNode,
    canOpenTerminal,
    canCapture,
    getTemplate,
    supportsConfig,
    canSaveConfig,
    loadConfig,
    saveConfigs,
    getConnection,
    peerLabel,
    adopt,
    bootstrap,
    load,
    createProject,
    closeProject,
    newLab,
    rename,
    addNode,
    updateNode,
    moveNode,
    autoAlign,
    setLinkOptimization,
    addAnnotation,
    updateAnnotation,
    moveAnnotation,
    connect,
    remove,
    save,
    saveProject,
    startJob,
    refresh,
    refreshEnvironment,
    refreshCatalog,
    deleteLab,
  };
});
