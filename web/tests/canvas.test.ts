import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import example from "../../examples/basic-lab.json";
import { clone, parseTopology, resizedPorts } from "../src/domain/topology";
import {
  alignDevices,
  annotationBox,
  crossesBox,
  nodeBox,
  nodeRadius,
  portAnchors,
  routeLink,
  type AlignMode,
} from "../src/domain/canvas";
import { useLabStore } from "../src/stores/lab";
import { useEditorStore } from "../src/stores/editor";
import type { Annotation } from "../src/types/lab";

const note = (): Annotation => ({
  id: "note-1",
  text: "网段：10.1.0.0/24\nOSPF Area 0",
  x: 120,
  y: 240,
  fontSize: 16,
  color: "#66521c",
  background: "#fff7d6",
});
beforeEach(() => setActivePinia(createPinia()));
describe("compact devices and visual routing", () => {
  it("ignores legacy rectangle dimensions for display but preserves them through JSON", () => {
    const topology = parseTopology(example),
      node = topology.nodes[0];
    expect(nodeRadius(node)).toBe(32);
    Object.assign(node, { width: 640, height: 640 });
    expect(nodeRadius(node)).toBe(32);
    expect(
      parseTopology(JSON.parse(JSON.stringify(topology))).nodes[0],
    ).toMatchObject({ width: 640, height: 640 });
    for (const value of [null, true, "150", NaN, Infinity, 0, 641]) {
      const raw = clone(example);
      Object.assign(raw.nodes[0], { width: value });
      expect(() => parseTopology(raw)).toThrow("尺寸");
    }
  });
  it("provides 32 distinct round port slots and scales only to keep them reachable", () => {
    const topology = parseTopology(example),
      node = topology.nodes[0];
    node.ports = resizedPorts(node, 32, topology);
    const ports = Object.values(portAnchors(topology)[node.id]);
    expect(new Set(ports.map((p) => `${p.x}:${p.y}`)).size).toBe(32);
    expect(nodeRadius(node)).toBeLessThanOrEqual(46);
    for (const p of ports)
      expect(Math.hypot(p.x - node.x, p.y - node.y)).toBeCloseTo(
        nodeRadius(node),
        1,
      );
  });
  it("uses nearest facing anchors and keeps endpoint identities when devices move", () => {
    const topology = parseTopology(example);
    topology.nodes = topology.nodes.slice(0, 2);
    topology.links = topology.links.slice(0, 1);
    Object.assign(topology.nodes[0], { x: 0, y: 0 });
    Object.assign(topology.nodes[1], { x: 300, y: 0 });
    const links = clone(topology.links),
      edge = topology.links[0];
    const anchors = portAnchors(topology),
      path = routeLink(topology, edge, anchors);
    expect(anchors.r1.eth0.x).toBe(32);
    expect(anchors.sw1.eth0.x).toBe(268);
    expect(path.d).toBe("M 32 0 L 268 0");
    topology.nodes[1].x = -300;
    expect(portAnchors(topology).r1.eth0.x).toBe(-32);
    expect(topology.links).toEqual(links);
    topology.optimizeLinks = false;
    expect(routeLink(topology, edge).d).toContain(" C ");
  });
  it("routes around an intermediate device and handles reversed and coincident endpoints", () => {
    const topology = parseTopology(example);
    topology.nodes = topology.nodes.slice(0, 3);
    topology.links = topology.links.slice(0, 1);
    Object.assign(topology.nodes[0], { x: 0, y: 0 });
    Object.assign(topology.nodes[1], { x: 400, y: 0 });
    Object.assign(topology.nodes[2], { x: 200, y: 0 });
    const route = routeLink(topology, topology.links[0]);
    expect(route.points.length).toBeGreaterThan(2);
    for (let i = 1; i < route.points.length; i++)
      expect(
        crossesBox(
          route.points[i - 1],
          route.points[i],
          nodeBox(topology.nodes[2], 12),
        ),
      ).toBe(false);
    const link = topology.links[0];
    expect(
      routeLink(topology, { ...link, a: link.b, b: link.a }).d,
    ).not.toMatch(/NaN|Infinity/);
    Object.assign(topology.nodes[1], { x: 0, y: 0 });
    expect(routeLink(topology, link).d).not.toMatch(/NaN|Infinity/);
  });
  it("keeps parallel links distinct without changing the selected interfaces", () => {
    const topology = parseTopology(example);
    topology.links.push({
      id: "parallel",
      a: { node: "r1", port: "eth2" },
      b: { node: "sw1", port: "eth2" },
    });
    const anchors = portAnchors(topology);
    expect(anchors.r1.eth0).not.toEqual(anchors.r1.eth2);
    expect(routeLink(topology, topology.links[0], anchors).d).not.toBe(
      routeLink(topology, topology.links.at(-1)!, anchors).d,
    );
  });
});
describe("automatic alignment", () => {
  it.each<AlignMode>(["layers", "horizontal", "vertical", "grid"])(
    "aligns %s without overlap or changing device settings and links",
    (mode) => {
      const lab = useLabStore();
      lab.adopt(parseTopology(example));
      lab.addAnnotation({ x: 10, y: 30 });
      const original = clone(lab.topology),
        positions = alignDevices(lab.topology, mode);
      lab.autoAlign(mode);
      expect(new Set(lab.topology.nodes.map((n) => `${n.x}:${n.y}`)).size).toBe(
        5,
      );
      for (const node of lab.topology.nodes) {
        expect(node).toEqual({
          ...original.nodes.find((n) => n.id === node.id),
          ...positions[node.id],
        });
        for (const other of lab.topology.nodes)
          if (other.id !== node.id)
            expect(
              Math.hypot(node.x - other.x, node.y - other.y),
            ).toBeGreaterThanOrEqual(144);
      }
      expect(lab.topology.links).toEqual(original.links);
      expect(lab.topology.annotations).toEqual(original.annotations);
      if (mode === "horizontal")
        expect(new Set(lab.topology.nodes.map((n) => n.y)).size).toBe(1);
      if (mode === "vertical")
        expect(new Set(lab.topology.nodes.map((n) => n.x)).size).toBe(1);
      expect(lab.dirty).toBe(true);
    },
  );
  it("handles cycles, isolated nodes and coordinate boundaries deterministically", () => {
    const topology = parseTopology(example);
    topology.links.push({
      id: "cycle",
      a: { node: "sw1", port: "eth2" },
      b: { node: "sw2", port: "eth2" },
    });
    topology.links = topology.links.filter((l) => l.b.node !== "pc2");
    for (const n of topology.nodes) {
      n.x = 99999;
      n.y = -99999;
    }
    const positions = alignDevices(topology, "layers");
    expect(alignDevices(topology, "layers")).toEqual(positions);
    expect(Object.keys(positions)).toHaveLength(5);
    for (const p of Object.values(positions)) {
      expect(Math.abs(p.x)).toBeLessThanOrEqual(100000);
      expect(Math.abs(p.y)).toBeLessThanOrEqual(100000);
    }
    expect(alignDevices({ ...topology, nodes: [], links: [] }, "grid")).toEqual(
      {},
    );
  });
});
describe("annotations", () => {
  it("round trips multiline text, styles and routing while keeping old JSON compatible", () => {
    const topology = parseTopology(example);
    expect(topology.annotations).toBeUndefined();
    topology.annotations = [note()];
    topology.optimizeLinks = false;
    expect(parseTopology(JSON.parse(JSON.stringify(topology)))).toEqual(
      topology,
    );
    const box = annotationBox(note());
    expect(box.lines).toHaveLength(2);
    expect(box.width).toBeGreaterThan(100);
    expect(
      annotationBox({ ...note(), text: "网".repeat(100) }).lines.length,
    ).toBeGreaterThan(1);
  });
  it("rejects malformed and oversized annotation data at import", () => {
    for (const patch of [
      { text: " " },
      { text: "a".repeat(1001) },
      { x: NaN },
      { y: 100001 },
      { color: "red;display:none" },
      { background: "url(x)" },
      { fontSize: true },
      { fontSize: 29 },
      { fontSize: 12.5 },
      { id: "../../escape" },
    ])
      expect(() =>
        parseTopology({ ...example, annotations: [{ ...note(), ...patch }] }),
      ).toThrow();
    expect(() =>
      parseTopology({ ...example, annotations: [note(), note()] }),
    ).toThrow("重复");
    expect(() =>
      parseTopology({
        ...example,
        annotations: Array.from({ length: 101 }, (_, i) => ({
          ...note(),
          id: `note-${i}`,
        })),
      }),
    ).toThrow("100");
    expect(() => parseTopology({ ...example, annotations: {} })).toThrow();
    expect(() => parseTopology({ ...example, optimizeLinks: "yes" })).toThrow();
  });
  it("preserves pending annotation text when dragging then saving, and deleting removes only the note", () => {
    const lab = useLabStore(),
      editor = useEditorStore();
    lab.adopt(parseTopology(example));
    editor.addAnnotation({ x: 10, y: 20 });
    const id = editor.annotation!.id;
    editor.annotationDraft!.text = "10.20.0.0/24\n业务网段";
    editor.touchDraft();
    lab.moveAnnotation(id, { x: 300, y: 400 });
    editor.commitDraft();
    expect(editor.annotation).toMatchObject({
      x: 300,
      y: 400,
      text: "10.20.0.0/24\n业务网段",
    });
    editor.deleteSelection();
    expect(lab.topology.annotations).toHaveLength(0);
    expect(lab.topology.nodes).toHaveLength(5);
    expect(lab.topology.links).toHaveLength(4);
  });
  it("keeps invalid annotation drafts selected and prevents changes when deployed", () => {
    const lab = useLabStore(),
      editor = useEditorStore();
    lab.adopt(parseTopology(example));
    editor.addAnnotation({ x: 10, y: 20 });
    const id = editor.annotation!.id;
    editor.annotationDraft!.text = " ";
    editor.touchDraft();
    expect(() => editor.select({ type: "node", id: "r1" })).toThrow();
    expect(editor.annotation!.id).toBe(id);
    lab.runtime = { phase: "running", deployment: "live", nodes: {}, logs: [] };
    expect(() => lab.moveAnnotation(id, { x: 5, y: 5 })).toThrow();
    expect(() => lab.remove("annotation", id)).toThrow();
  });
});
