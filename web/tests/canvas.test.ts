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
  scrollBounds,
} from "../src/domain/canvas";
import { useLabStore } from "../src/stores/lab";
import { useEditorStore } from "../src/stores/editor";
import type { Annotation, Point } from "../src/types/lab";

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
  function layout(points: Point[]) {
    const topology = parseTopology(example);
    topology.nodes = topology.nodes.slice(0, points.length);
    topology.nodes.forEach((node, i) => Object.assign(node, points[i]));
    topology.links = topology.links.filter((link) =>
      [link.a.node, link.b.node].every((id) =>
        topology.nodes.some((n) => n.id === id),
      ),
    );
    return topology;
  }
  const nearbyGrid = () =>
    layout([
      { x: 100, y: 100 },
      { x: 300, y: 112 },
      { x: 118, y: 300 },
      { x: 312, y: 324 },
      { x: 600, y: 600 },
    ]);

  it("aligns nearby rows and columns while preserving settings, links, notes and viewport", () => {
    const lab = useLabStore(),
      editor = useEditorStore();
    lab.adopt(nearbyGrid());
    lab.addAnnotation({ x: 10, y: 30 });
    lab.dirty = false;
    const original = clone(lab.topology),
      view = clone(editor.view);
    expect(lab.autoAlign()).toBe(3);
    expect(lab.topology.nodes.map(({ x, y }) => ({ x, y }))).toEqual([
      { x: 100, y: 100 },
      { x: 300, y: 100 },
      { x: 100, y: 300 },
      { x: 300, y: 300 },
      { x: 600, y: 600 },
    ]);
    for (const node of lab.topology.nodes) {
      expect(node).toEqual({
        ...original.nodes.find((n) => n.id === node.id),
        x: node.x,
        y: node.y,
      });
    }
    expect(lab.topology.links).toEqual(original.links);
    expect(lab.topology.annotations).toEqual(original.annotations);
    expect(editor.view).toEqual(view);
    expect(lab.dirty).toBe(true);
    lab.dirty = false;
    expect(lab.autoAlign()).toBe(0);
    expect(lab.dirty).toBe(false);
  });

  it.each([23, 24, 25])(
    "only snaps coordinates within 24 canvas units (gap %s)",
    (gap) => {
      for (const axis of ["x", "y"] as const) {
        const other = axis === "x" ? "y" : "x";
        const topology = layout([
          { x: 100, y: 100 },
          { x: 100, y: 100 },
        ]);
        topology.nodes[1][axis] += gap;
        topology.nodes[1][other] += 200;
        const positions = alignDevices(topology);
        expect(positions.sw1[axis]).toBe(gap <= 24 ? 100 : 100 + gap);
        expect(positions.sw1[other]).toBe(300);
      }
    },
  );

  it("bounds each whole group instead of chaining distant devices together", () => {
    const topology = layout([
      { x: 0, y: 0 },
      { x: 23, y: 200 },
      { x: 25, y: 400 },
    ]);
    const positions = alignDevices(topology);
    expect(positions).toEqual({
      r1: { x: 0, y: 0 },
      sw1: { x: 0, y: 200 },
      sw2: { x: 25, y: 400 },
    });
    topology.nodes.forEach((n) => Object.assign(n, positions[n.id]));
    expect(alignDevices(topology)).toEqual(positions);
  });

  it("is independent of input order and connections, leaves input unchanged and is idempotent", () => {
    const topology = nearbyGrid(),
      original = clone(topology);
    const positions = alignDevices(topology);
    expect(topology).toEqual(original);
    expect(
      alignDevices({
        ...topology,
        nodes: [...topology.nodes].reverse(),
        links: [],
      }),
    ).toEqual(positions);
    topology.nodes.forEach((n) => Object.assign(n, positions[n.id]));
    expect(alignDevices(topology)).toEqual(positions);
  });

  it("skips moves that overlap devices or their name area while aligning safe devices", () => {
    const topology = layout([
      { x: 0, y: 0 },
      { x: 0, y: 200 },
      { x: 60, y: 292 },
      { x: 200, y: 280 },
      { x: 212, y: 600 },
    ]);
    const positions = alignDevices(topology);
    expect(positions.sw2).toEqual({ x: 60, y: 292 });
    expect(positions.pc2).toEqual({ x: 200, y: 600 });
    topology.nodes.forEach((n) => Object.assign(n, positions[n.id]));
    expect(alignDevices(topology)).toEqual(positions);
  });

  it("does not collapse nearly coincident devices", () => {
    const topology = layout([
      { x: 0, y: 0 },
      { x: 10, y: 12 },
    ]);
    expect(alignDevices(topology)).toEqual({
      r1: { x: 0, y: 0 },
      sw1: { x: 10, y: 12 },
    });
  });

  it("accounts for the larger circles on 32-port devices", () => {
    const topology = layout([
      { x: 0, y: 0 },
      { x: 85, y: 120 },
      { x: 300, y: 100 },
    ]);
    topology.nodes.slice(0, 2).forEach((node) => {
      node.ports = resizedPorts(node, 32, topology);
    });
    expect(alignDevices(topology).sw1).toEqual({ x: 85, y: 120 });
  });

  it("preserves separated, single and empty layouts without making the project dirty", () => {
    for (const points of [
      [],
      [{ x: 0, y: 0 }],
      [
        { x: -100000, y: -100000 },
        { x: 100000, y: 100000 },
      ],
    ]) {
      const lab = useLabStore();
      lab.adopt(layout(points));
      lab.dirty = false;
      const original = clone(lab.topology);
      expect(lab.autoAlign()).toBe(0);
      expect(lab.topology).toEqual(original);
      expect(lab.dirty).toBe(false);
    }
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
    expect(() => lab.moveAnnotation(id, { x: 5, y: 5 })).not.toThrow();
    expect(editor.annotation).toMatchObject({ x: 5, y: 5 });
    expect(() =>
      lab.updateAnnotation({ ...editor.annotation!, text: "changed" }),
    ).toThrow();
    expect(() => lab.remove("annotation", id)).toThrow();
  });
});
describe("scrollable workspace", () => {
  it.each([0.25, 1, 2.5])(
    "covers distant and negative content plus panning space at scale %s",
    (scale) => {
      const boxes = [
        nodeBox({ ...parseTopology(example).nodes[0], x: -100000, y: 100000 }),
        annotationBox(note()),
      ];
      const bounds = scrollBounds(boxes, 800, 500, scale);
      for (const box of boxes) {
        expect(bounds.left).toBeLessThan(box.left);
        expect(bounds.right).toBeGreaterThan(box.right);
        expect(bounds.top).toBeLessThan(box.top);
        expect(bounds.bottom).toBeGreaterThan(box.bottom);
      }
      const empty = scrollBounds([], 800, 500, scale);
      expect((empty.right - empty.left) * scale).toBeGreaterThan(800);
      expect((empty.bottom - empty.top) * scale).toBeGreaterThan(500);
    },
  );
});
