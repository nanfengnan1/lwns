import type {
  Annotation,
  Device,
  DeviceKind,
  Endpoint,
  Link,
  Phase,
  Topology,
} from "../types/lab";

export const titles: Record<DeviceKind, string> = {
  router: "FRR 路由器",
  switch: "以太网交换机",
  host: "VPCS 终端",
  firewall: "防火墙",
};
export const colors: Record<DeviceKind, string> = {
  router: "#6484dd",
  switch: "#43a48f",
  host: "#9b7bc5",
  firewall: "#d48a48",
};
export const phases: Record<Phase, string> = {
  idle: "设计中",
  running: "运行中",
  deploying: "正在部署",
  updating: "正在应用拓扑",
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

export function projectName(value: unknown): string {
  return string(value, "项目名称（1–80 个字符）", 80);
}

export function parseAnnotation(value: unknown): Annotation {
  const raw = record(value);
  for (const key of ["x", "y"] as const) {
    if (
      typeof raw[key] !== "number" ||
      !Number.isFinite(raw[key]) ||
      Math.abs(raw[key]) > 100000
    )
      throw Error("注释坐标无效");
  }
  const fontSize = raw.fontSize ?? 16;
  const color = raw.color ?? "#66521c",
    background = raw.background ?? "#fff7d6";
  if (
    typeof fontSize !== "number" ||
    !Number.isInteger(fontSize) ||
    fontSize < 12 ||
    fontSize > 28
  )
    throw Error("注释字号必须为 12–28 的整数");
  if (
    typeof color !== "string" ||
    !/^#[0-9a-fA-F]{6}$/.test(color) ||
    typeof background !== "string" ||
    (background !== "none" && !/^#[0-9a-fA-F]{6}$/.test(background))
  )
    throw Error("注释颜色无效");
  return {
    id: identifier(raw.id),
    x: raw.x as number,
    y: raw.y as number,
    text: string(raw.text, "注释内容（1–1000 个字符）", 1000),
    fontSize,
    color,
    background,
  };
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
    if (!["router", "switch", "host", "firewall"].includes(String(node.kind)))
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
  if (raw.optimizeLinks !== undefined && typeof raw.optimizeLinks !== "boolean")
    throw Error("连线优化选项必须为布尔值");
  if (
    raw.annotations !== undefined &&
    (!Array.isArray(raw.annotations) || raw.annotations.length > 100)
  )
    throw Error("最多支持 100 条注释");
  const annotations = (raw.annotations as unknown[] | undefined)?.map(
    parseAnnotation,
  );
  if (
    annotations &&
    new Set(annotations.map((item) => item.id)).size !== annotations.length
  )
    throw Error("注释 ID 重复");
  return {
    version: 1,
    id: identifier(raw.id),
    name: string(raw.name, "实验名称", 80),
    nodes,
    links,
    ...(annotations === undefined ? {} : { annotations }),
    ...(raw.optimizeLinks === undefined
      ? {}
      : { optimizeLinks: raw.optimizeLinks as boolean }),
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
