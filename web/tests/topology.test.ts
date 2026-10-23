import { describe, expect, it } from "vitest";
import example from "../../examples/basic-lab.json";
import {
  assertConnection,
  clone,
  parseTopology,
  resizedPorts,
} from "../src/domain/topology";

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
