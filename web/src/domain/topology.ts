import type {
  Device,
  DeviceKind,
  Endpoint,
  Link,
  Phase,
  Point,
  Topology,
} from "../types/lab";

export const titles: Record<DeviceKind, string> = {
  router: "FRR 路由器",
  switch: "以太网交换机",
  host: "VPCS 终端",
};
export const colors: Record<DeviceKind, string> = {
  router: "#6484dd",
  switch: "#43a48f",
  host: "#9b7bc5",
};
export const phases: Record<Phase, string> = {
  idle: "设计中",
  running: "运行中",
  deploying: "正在部署",
  destroying: "正在清理",
  error: "操作失败",
  degraded: "需要检查",
};
export const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const idPattern = /^[a-z0-9][a-z0-9_-]{0,31}$/;
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("拓扑对象格式无效");
  return value as Record<string, unknown>;
}
function string(
  value: unknown,
  label: string,
  max: number,
  empty = false,
): string {
  if (
    typeof value !== "string" ||
    value.includes("\0") ||
    value.length > max ||
    (!empty && !value.trim())
  )
    throw Error(`${label}格式无效`);
  return value.trim();
}
function identifier(value: unknown): string {
  if (typeof value !== "string" || !idPattern.test(value))
    throw Error("ID 格式无效");
  return value;
}

// Imported JSON is untrusted at runtime, even in a TypeScript application.
// IP/subnet semantics remain authoritative on the Python backend.
export function parseTopology(value: unknown): Topology {
  const raw = record(value);
  if (
    raw.version !== 1 ||
    !Array.isArray(raw.nodes) ||
    !Array.isArray(raw.links) ||
    raw.nodes.length > 64 ||
    raw.links.length > 256
  )
    throw Error("不支持的拓扑格式，最多 64 台设备和 256 条链路");
  const ids = new Set<string>(),
    names = new Set<string>();
  const nodes: Device[] = raw.nodes.map((value) => {
    const node = record(value),
      id = identifier(node.id);
    const name = string(node.name, "设备名称", 32);
    if (
      !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$/.test(name) ||
      ids.has(id) ||
      names.has(name)
    )
      throw Error("设备 ID 或名称重复或无效");
    if (!["router", "switch", "host"].includes(String(node.kind)))
      throw Error("设备类型无效");
    if (
      typeof node.x !== "number" ||
      typeof node.y !== "number" ||
      !Number.isFinite(node.x) ||
      !Number.isFinite(node.y) ||
      Math.abs(node.x) > 100000 ||
      Math.abs(node.y) > 100000
    )
      throw Error("设备坐标无效");
    if (
      !Array.isArray(node.ports) ||
      node.ports.length < 1 ||
      node.ports.length > 32
    )
      throw Error("端口数必须为 1–32");
    const portNames = new Set<string>();
    const size: Pick<Device, "width" | "height"> = {};
    for (const [key, minimum] of [
      ["width", 96],
      ["height", 72],
    ] as const) {
      if (!(key in node)) continue;
      const value = node[key];
      if (
        typeof value !== "number" ||
        !Number.isFinite(value) ||
        value < minimum ||
        value > 640
      )
        throw Error(`设备尺寸无效：${key} 必须为 ${minimum}–640`);
      size[key] = value;
    }
    const ports = node.ports.map((value) => {
      const port = record(value),
        name = string(port.name, "端口名称", 15);
      if (
        !/^[A-Za-z][A-Za-z0-9_.-]{0,14}$/.test(name) ||
        ["lo", "br0"].includes(name) ||
        portNames.has(name)
      )
        throw Error("端口名称重复或无效");
      portNames.add(name);
      return {
        name,
        address: string(port.address ?? "", "端口地址", 64, true),
      };
    });
    const command = node.command ?? [];
    if (
      !Array.isArray(command) ||
      command.length > 64 ||
      command.some(
        (arg) =>
          typeof arg !== "string" ||
          !arg ||
          arg.length > 4096 ||
          arg.includes("\0"),
      )
    )
      throw Error("启动命令必须是字符串数组");
    const image = string(node.image, "镜像", 255);
    if (!/^[A-Za-z0-9][A-Za-z0-9_./:@-]*$/.test(image))
      throw Error("镜像名称无效");
    ids.add(id);
    names.add(name);
    return {
      id,
      name,
      kind: node.kind as DeviceKind,
      ...(node.template === undefined
        ? {}
        : { template: identifier(node.template) }),
      image,
      x: node.x,
      y: node.y,
      ...size,
      ports,
      gateway: string(node.gateway ?? "", "默认网关", 64, true),
      command,
      config: string(node.config ?? "", "FRR 配置", 32768, true),
    };
  });
  const used = new Set<string>(),
    linkIds = new Set<string>();
  const links: Link[] = raw.links.map((value) => {
    const link = record(value),
      id = identifier(link.id);
    if (linkIds.has(id)) throw Error("链路 ID 重复");
    linkIds.add(id);
    const endpoint = (value: unknown): Endpoint => {
      const end = record(value),
        node = identifier(end.node),
        port = string(end.port, "端口名称", 15);
      if (
        !nodes.find((n) => n.id === node)?.ports.some((p) => p.name === port) ||
        used.has(`${node}:${port}`)
      )
        throw Error("链路端点不存在或端口重复连接");
      used.add(`${node}:${port}`);
      return { node, port };
    };
    const a = endpoint(link.a),
      b = endpoint(link.b);
    if (a.node === b.node) throw Error("不支持设备自身环回连接");
    return { id, a, b };
  });
  return {
    version: 1,
    id: identifier(raw.id),
    name: string(raw.name, "实验名称", 80),
    nodes,
    links,
  };
}

export function connection(topology: Topology, node: string, port: string) {
  return topology.links.find((link) =>
    [link.a, link.b].some((end) => end.node === node && end.port === port),
  );
}
export function assertConnection(
  topology: Topology,
  a: Endpoint,
  b?: Endpoint,
) {
  for (const end of b ? [a, b] : [a]) {
    if (
      !topology.nodes
        .find((n) => n.id === end.node)
        ?.ports.some((p) => p.name === end.port)
    )
      throw Error("链路端点不存在");
    if (connection(topology, end.node, end.port))
      throw Error("这个端口已经连接了网线");
  }
  if (b?.node === a.node) throw Error("请选择另一台设备的空闲端口");
  if (b && topology.links.length >= 256) throw Error("最多支持 256 条链路");
}
export function resizedPorts(node: Device, count: number, topology: Topology) {
  if (!Number.isInteger(count) || count < 1 || count > 32)
    throw Error("端口数必须为 1–32");
  if (
    node.ports.slice(count).some((p) => connection(topology, node.id, p.name))
  )
    throw Error("待移除端口仍有网线，请先删除网线");
  const ports = clone(node.ports.slice(0, count));
  while (ports.length < count) {
    let i = 0;
    while (ports.some((p) => p.name === `eth${i}`)) i++;
    ports.push({ name: `eth${i}`, address: "" });
  }
  return ports;
}
export function uniqueId(prefix: string): string {
  // getRandomValues also works when accessing a Linux host over plain HTTP.
  return (
    prefix +
    Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("")
  );
}
export type ResizeHandle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";
export interface NodeBounds extends Point {
  width: number;
  height: number;
}
export const nodeWidth = (node: Device) => node.width ?? 128;
export const nodeMinHeight = (node: Device) =>
  Math.max(72, Math.ceil(node.ports.length / 2) * 13 + 20);
export const nodeHeight = (node: Device) =>
  Math.max(node.height ?? 100, nodeMinHeight(node));
export function resizeNodeBounds(
  node: Device,
  handle: ResizeHandle,
  delta: Point,
): NodeBounds {
  const width = nodeWidth(node),
    height = nodeHeight(node);
  const horizontal = handle.includes("e") ? 1 : handle.includes("w") ? -1 : 0;
  const vertical = handle.includes("s") ? 1 : handle.includes("n") ? -1 : 0;
  // Keep the opposite edge fixed, including when a minimum/maximum is reached.
  const dx = Math.max(
    -2 * (100000 + node.x),
    Math.min(2 * (100000 - node.x), delta.x),
  );
  const dy = Math.max(
    -2 * (100000 + node.y),
    Math.min(2 * (100000 - node.y), delta.y),
  );
  const nextWidth = Math.max(96, Math.min(640, width + horizontal * dx));
  const nextHeight = Math.max(
    nodeMinHeight(node),
    Math.min(640, height + vertical * dy),
  );
  return {
    x: node.x + (horizontal * (nextWidth - width)) / 2,
    y: node.y + (vertical * (nextHeight - height)) / 2,
    width: nextWidth,
    height: nextHeight,
  };
}
export function portPoint(
  node: Device,
  name: string,
): Point & { side: number } {
  const index = node.ports.findIndex((p) => p.name === name),
    rows = Math.ceil(node.ports.length / 2);
  return {
    x: node.x + ((index % 2 ? 1 : -1) * nodeWidth(node)) / 2,
    y:
      node.y +
      (rows === 1
        ? 0
        : -nodeHeight(node) / 2 +
          15 +
          (Math.floor(index / 2) * (nodeHeight(node) - 30)) / (rows - 1)),
    side: index % 2 ? 1 : -1,
  };
}
