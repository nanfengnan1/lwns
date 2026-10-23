import { describe, expect, it } from "vitest";
import example from "../../examples/basic-lab.json";
import {
  assertConnection,
  clone,
  nodeHeight,
  nodeWidth,
  parseTopology,
  portPoint,
  resizeNodeBounds,
  resizedPorts,
} from "../src/domain/topology";
import type { ResizeHandle } from "../src/domain/topology";

describe("version 1 topology compatibility and graph rules", () => {
  it("round trips the existing five-device example without losing addresses or endpoints", () => {
    const topology = parseTopology(example);
    expect(parseTopology(JSON.parse(JSON.stringify(topology)))).toEqual(
      topology,
    );
    expect(topology.nodes).toHaveLength(5);
    expect(topology.links).toEqual(example.links);
    expect(topology.nodes.find((n) => n.id === "pc1")?.gateway).toBe(
      "10.10.1.1",
    );
  });
  it("rejects malformed command and port values before adopting an import", () => {
    const topology = clone(example) as unknown as {
      nodes: Record<string, unknown>[];
    };
    topology.nodes[0].command = "sh -c bad";
    expect(() => parseTopology(topology)).toThrow("字符串数组");
    topology.nodes[0].command = [];
    topology.nodes[0].ports = [{ name: "lo" }];
    expect(() => parseTopology(topology)).toThrow("端口");
  });
  it("rejects duplicate nodes, missing endpoints and port reuse", () => {
    const duplicate = parseTopology(example);
    duplicate.nodes.push(clone(duplicate.nodes[0]));
    expect(() => parseTopology(duplicate)).toThrow("重复");
    const missing = parseTopology(example);
    missing.links[0].a.node = "missing";
    expect(() => parseTopology(missing)).toThrow("端点");
    const reused = parseTopology(example);
    reused.links.push({ ...clone(reused.links[0]), id: "extra" });
    expect(() => parseTopology(reused)).toThrow("重复连接");
  });
  it("accepts free ports in either direction and blocks loops and occupied ports", () => {
    const topology = parseTopology(example),
      a = { node: "r1", port: "eth2" },
      b = { node: "sw1", port: "eth2" };
    expect(() => assertConnection(topology, a, b)).not.toThrow();
    expect(() => assertConnection(topology, b, a)).not.toThrow();
    expect(() =>
      assertConnection(topology, a, { node: "r1", port: "eth3" }),
    ).toThrow("另一台");
    expect(() =>
      assertConnection(topology, { node: "pc1", port: "eth0" }, a),
    ).toThrow("已经连接");
  });
  it("preserves connected ports while growing and refuses to truncate one", () => {
    const topology = parseTopology(example),
      node = topology.nodes.find((n) => n.id === "r1")!;
    expect(resizedPorts(node, 6, topology).map((p) => p.name)).toEqual([
      "eth0",
      "eth1",
      "eth2",
      "eth3",
      "eth4",
      "eth5",
    ]);
    expect(() => resizedPorts(node, 1, topology)).toThrow("仍有网线");
  });
});

describe("device canvas sizing", () => {
  it("keeps legacy defaults and preserves optional dimensions through JSON", () => {
    const topology = parseTopology(example),
      node = topology.nodes[0];
    expect(nodeWidth(node)).toBe(128);
    expect(nodeHeight(node)).toBe(100);
    expect(node).not.toHaveProperty("width");
    Object.assign(node, { width: 215.5, height: 136 });
    expect(parseTopology(JSON.parse(JSON.stringify(topology)))).toEqual(
      topology,
    );
  });
  it("rejects nonnumeric, nonfinite and out-of-range dimensions", () => {
    for (const key of ["width", "height"]) {
      for (const value of [null, true, "150", NaN, Infinity, 0, -1, 641]) {
        const raw = clone(example);
        Object.assign(raw.nodes[0], { [key]: value });
        expect(() => parseTopology(raw)).toThrow("尺寸");
      }
    }
  });
  it.each<ResizeHandle>(["n", "s", "e", "w", "ne", "nw", "se", "sw"])(
    "resizes %s while anchoring the opposite edge and leaving other axes unchanged",
    (handle) => {
      const node = { ...parseTopology(example).nodes[0], x: 200, y: 200 };
      const horizontal = handle.includes("e")
        ? 1
        : handle.includes("w")
          ? -1
          : 0;
      const vertical = handle.includes("s") ? 1 : handle.includes("n") ? -1 : 0;
      const result = resizeNodeBounds(node, handle, {
        x: horizontal * 40,
        y: vertical * 30,
      });
      expect(result).toEqual({
        x: 200 + horizontal * 20,
        y: 200 + vertical * 15,
        width: horizontal ? 168 : 128,
        height: vertical ? 130 : 100,
      });
      expect(
        resizeNodeBounds({ ...node, ...result }, handle, {
          x: -horizontal * 40,
          y: -vertical * 30,
        }),
      ).toEqual({ x: 200, y: 200, width: 128, height: 100 });
    },
  );
  it("clamps size and coordinates while maintaining the fixed edges", () => {
    const node = { ...parseTopology(example).nodes[0], x: 0, y: 0 };
    expect(resizeNodeBounds(node, "nw", { x: 10000, y: 10000 })).toEqual({
      x: 16,
      y: 14,
      width: 96,
      height: 72,
    });
    expect(resizeNodeBounds(node, "se", { x: 10000, y: 10000 })).toEqual({
      x: 256,
      y: 270,
      width: 640,
      height: 640,
    });
    const atBoundary = resizeNodeBounds(
      { ...node, x: 99999, y: -99999 },
      "ne",
      { x: 100, y: -100 },
    );
    expect(atBoundary).toEqual({
      x: 100000,
      y: -100000,
      width: 130,
      height: 102,
    });
  });
  it("keeps ports on resized edges and reserves height for 32 ports", () => {
    const topology = parseTopology(example),
      node = topology.nodes[0];
    Object.assign(node, { x: 200, y: 200, width: 200, height: 160 });
    expect(portPoint(node, "eth0")).toEqual({ x: 100, y: 135, side: -1 });
    expect(portPoint(node, "eth3")).toEqual({ x: 300, y: 265, side: 1 });
    node.ports = resizedPorts(node, 32, topology);
    expect(nodeHeight(node)).toBe(228);
    expect(resizeNodeBounds(node, "n", { x: 0, y: 10000 }).height).toBe(228);
  });
});
