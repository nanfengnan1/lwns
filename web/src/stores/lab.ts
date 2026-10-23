import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { api } from "../api/client";
import {
  assertConnection,
  clone,
  connection,
  nodeMinHeight,
  parseTopology,
  uniqueId,
} from "../domain/topology";
import type { NodeBounds } from "../domain/topology";
import type {
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
  Runtime,
  Topology,
} from "../types/lab";

export const useLabStore = defineStore("lab", () => {
  const topology = ref<Topology>({
    version: 1,
    id: "new-lab",
    name: "新建实验",
    nodes: [],
    links: [],
  });
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
  const example = ref<Topology | null>(null);
  const saved = ref(false),
    dirty = ref(false),
    busy = ref(false);
  const operation = ref(""),
    documentVersion = ref(0);
  const locked = computed(
    () => busy.value || !!runtime.value?.deployment || !!operation.value,
  );
  const phase = computed(() => runtime.value?.phase || "idle");
  const images = computed(() => [
    ...new Set([
      ...environment.value.images,
      ...catalog.value.map((item) => item.image),
    ]),
  ]);
  const canDeploy = computed(
    () =>
      !locked.value &&
      environment.value.ready &&
      topology.value.nodes.length > 0,
  );
  const canDestroy = computed(
    () =>
      saved.value &&
      !!runtime.value?.deployment &&
      environment.value.ready &&
      !busy.value &&
      !operation.value,
  );
  let refreshing = false;
  let runtimeRevision = 0;

  function assertEditable() {
    if (locked.value) throw Error("请等待操作完成，并清理设备后再编辑拓扑");
  }
  function getNode(id: string) {
    return topology.value.nodes.find((node) => node.id === id);
  }
  function getTemplate(node: Device) {
    return catalog.value.find((item) =>
      node.template ? item.id === node.template : item.kind === node.kind,
    );
  }
  function supportsConfig(node: Device) {
    return (
      getTemplate(node)?.capabilities?.save_config ??
      (!node.template && node.kind === "router")
    );
  }
  function canSaveConfig(nodeId?: string) {
    return (
      saved.value &&
      !!runtime.value?.deployment &&
      environment.value.ready &&
      !busy.value &&
      !operation.value &&
      !["deploying", "destroying"].includes(phase.value) &&
      topology.value.nodes.some(
        (node) =>
          (!nodeId || node.id === nodeId) &&
          supportsConfig(node) &&
          runtime.value?.nodes[node.id],
      )
    );
  }
  async function loadConfig(nodeId: string) {
    if (!saved.value || operation.value) return;
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
        if (node && item.config !== undefined) node.config = item.config;
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
      example.value = data.example;
      if (data.labs.length) {
        const record = await api<LabRecord>(`/api/labs/${data.labs[0].id}`);
        adopt(record.topology, record);
      } else adopt(data.example);
    } finally {
      operation.value = "";
    }
  }
  async function load(id: string) {
    if (operation.value) return;
    operation.value = "load";
    try {
      const record = await api<LabRecord>(`/api/labs/${id}`);
      adopt(record.topology, record);
    } finally {
      operation.value = "";
    }
  }
  function newLab() {
    if (operation.value) return;
    adopt({
      version: 1,
      id: uniqueId("lab-"),
      name: "未命名实验",
      nodes: [],
      links: [],
    });
  }
  function loadExample() {
    if (operation.value || !example.value) return;
    adopt({ ...clone(example.value), id: uniqueId("lab-") });
  }
  function rename(name: string) {
    assertEditable();
    topology.value.name = name || "未命名实验";
    dirty.value = true;
  }
  function addNode(templateId: string, point: Point) {
    assertEditable();
    if (topology.value.nodes.length >= 64) throw Error("最多支持 64 台设备");
    const template = catalog.value.find(
      (item) => item.id === templateId || item.kind === templateId,
    );
    if (!template) throw Error("未知设备类型");
    const kind = template.kind;
    const prefix = kind === "router" ? "r" : kind === "switch" ? "sw" : "pc";
    let i = 1;
    while (getNode(prefix + i)) i++;
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
    assertEditable();
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
  function resizeNode(id: string, bounds: NodeBounds) {
    assertEditable();
    const node = getNode(id);
    if (!node) return;
    moveNode(id, bounds);
    node.width = Math.max(96, Math.min(640, bounds.width));
    node.height = Math.max(nodeMinHeight(node), Math.min(640, bounds.height));
  }
  function resetNodeSize(id: string) {
    assertEditable();
    const node = getNode(id);
    if (!node) return;
    delete node.width;
    delete node.height;
    dirty.value = true;
  }
  function remove(type: "node" | "link", id: string) {
    assertEditable();
    if (type === "node") {
      topology.value.nodes = topology.value.nodes.filter((n) => n.id !== id);
      topology.value.links = topology.value.links.filter(
        (link) => link.a.node !== id && link.b.node !== id,
      );
    } else
      topology.value.links = topology.value.links.filter(
        (link) => link.id !== id,
      );
    dirty.value = true;
  }
  async function save() {
    assertEditable();
    const payload = parseTopology(topology.value);
    runtimeRevision++;
    operation.value = "save";
    try {
      const record = await api<LabRecord>(
        `/api/labs/${payload.id}`,
        "PUT",
        payload,
      );
      topology.value = record.topology;
      runtime.value = record.runtime;
      saved.value = true;
      dirty.value = false;
      labs.value = await api<LabSummary[]>("/api/labs");
    } finally {
      operation.value = "";
    }
  }
  async function startJob(action: "deploy" | "destroy") {
    if (action === "deploy" ? !canDeploy.value : !canDestroy.value)
      throw Error("当前状态不允许执行此操作");
    if (action === "deploy" && (!saved.value || dirty.value)) await save();
    runtimeRevision++;
    operation.value = action;
    try {
      const record = await api<LabRecord>(
        `/api/labs/${topology.value.id}/${action}`,
        "POST",
        {},
      );
      runtime.value = record.runtime;
      busy.value = true;
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
      runtime.value = record.runtime;
      busy.value = !!record.busy;
    } finally {
      refreshing = false;
    }
  }
  async function refreshEnvironment() {
    environment.value = await api<Environment>("/api/environment");
    await refresh();
  }
  async function refreshCatalog() {
    catalog.value = await api<DeviceTemplate[]>("/api/catalog");
  }
  async function deleteLab() {
    assertEditable();
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
      adopt({
        version: 1,
        id: uniqueId("lab-"),
        name: "未命名实验",
        nodes: [],
        links: [],
      });
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
    example,
    saved,
    dirty,
    busy,
    operation,
    documentVersion,
    locked,
    phase,
    images,
    canDeploy,
    canDestroy,
    assertEditable,
    getNode,
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
    newLab,
    loadExample,
    rename,
    addNode,
    updateNode,
    moveNode,
    resizeNode,
    resetNodeSize,
    connect,
    remove,
    save,
    startJob,
    refresh,
    refreshEnvironment,
    refreshCatalog,
    deleteLab,
  };
});
