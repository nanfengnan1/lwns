import type { Annotation, Device, Link, Point, Topology } from "../types/lab";

export const ALIGN_TOLERANCE = 24;
export type Anchor = Point & { dx: number; dy: number };
export const nodeRadius = (node: Device) =>
  Math.max(32, Math.ceil((node.ports.length * 9) / (2 * Math.PI)));
const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);
const round = (n: number) => Math.round(n * 100) / 100;

/** Assign visual slots toward peers without ever changing actual interface IDs. */
export function portAnchors(
  topology: Topology,
): Record<string, Record<string, Anchor>> {
  const nodes = new Map(topology.nodes.map((node) => [node.id, node]));
  const result: Record<string, Record<string, Anchor>> = {};
  for (const node of topology.nodes) {
    const count = Math.max(8, node.ports.length),
      radius = nodeRadius(node);
    const slots = Array.from(
      { length: count },
      (_, i) => Math.PI + (i * 2 * Math.PI) / count,
    );
    const used = new Set<number>(),
      anchors: Record<string, Anchor> = {};
    const desired = new Map<string, number>();
    if (topology.optimizeLinks !== false) {
      for (const link of topology.links) {
        const end =
          link.a.node === node.id
            ? link.a
            : link.b.node === node.id
              ? link.b
              : null;
        if (!end) continue;
        const peer = nodes.get(end === link.a ? link.b.node : link.a.node);
        if (peer)
          desired.set(end.port, Math.atan2(peer.y - node.y, peer.x - node.x));
      }
    }
    // Stable priority makes connected ports face their peers, then places free ports.
    const ports = [...node.ports].sort(
      (a, b) => Number(desired.has(b.name)) - Number(desired.has(a.name)),
    );
    for (const port of ports) {
      const index = node.ports.indexOf(port);
      const angle =
        desired.get(port.name) ??
        Math.PI + (index * 2 * Math.PI) / node.ports.length;
      let best = -1,
        score = Infinity;
      slots.forEach((slot, i) => {
        const delta = Math.abs(
          Math.atan2(Math.sin(slot - angle), Math.cos(slot - angle)),
        );
        if (!used.has(i) && delta < score - 1e-9) {
          best = i;
          score = delta;
        }
      });
      used.add(best);
      const dx = Math.cos(slots[best]),
        dy = Math.sin(slots[best]);
      anchors[port.name] = {
        x: round(node.x + dx * radius),
        y: round(node.y + dy * radius),
        dx,
        dy,
      };
    }
    result[node.id] = anchors;
  }
  return result;
}

export interface Box {
  left: number;
  right: number;
  top: number;
  bottom: number;
}
/** A finite scrollable workspace, including negative coordinates and room to pan. */
export function scrollBounds(
  boxes: Box[],
  width: number,
  height: number,
  scale: number,
): Box {
  const w = Math.max(1, width) / scale,
    h = Math.max(1, height) / scale;
  const paddingX = Math.max(400, w),
    paddingY = Math.max(400, h);
  return {
    left: Math.min(0, ...boxes.map((box) => box.left)) - paddingX,
    right: Math.max(w, ...boxes.map((box) => box.right)) + paddingX,
    top: Math.min(0, ...boxes.map((box) => box.top)) - paddingY,
    bottom: Math.max(h, ...boxes.map((box) => box.bottom)) + paddingY,
  };
}
export function nodeBox(node: Device, padding = 0): Box {
  const r = nodeRadius(node) + padding;
  return {
    left: node.x - r,
    right: node.x + r,
    top: node.y - r,
    bottom: node.y + r + 25,
  };
}
export function annotationBox(note: Annotation) {
  const lines: string[] = [];
  for (const paragraph of note.text.split(/\r?\n/)) {
    let line = "",
      units = 0;
    for (const char of paragraph) {
      const width = char.charCodeAt(0) < 128 ? 0.6 : 1;
      if (units + width > 24) {
        lines.push(line);
        line = "";
        units = 0;
      }
      line += char;
      units += width;
    }
    lines.push(line);
  }
  const width = Math.max(
    100,
    ...lines.map(
      (line) =>
        [...line].reduce(
          (n, char) => n + (char.charCodeAt(0) < 128 ? 0.6 : 1),
          0,
        ) *
          note.fontSize +
        24,
    ),
  );
  const height = lines.length * note.fontSize * 1.5 + 20;
  return {
    left: note.x,
    top: note.y,
    right: note.x + width,
    bottom: note.y + height,
    width,
    height,
    lines,
  };
}

/** Test the interior, allowing a route along the padded box boundary. */
export function crossesBox(a: Point, b: Point, box: Box): boolean {
  let lo = 0,
    hi = 1;
  for (const [start, delta, min, max] of [
    [a.x, b.x - a.x, box.left + 0.01, box.right - 0.01],
    [a.y, b.y - a.y, box.top + 0.01, box.bottom - 0.01],
  ]) {
    if (Math.abs(delta) < 1e-9) {
      if (start < min || start > max) return false;
    } else {
      const t1 = (min - start) / delta,
        t2 = (max - start) / delta;
      lo = Math.max(lo, Math.min(t1, t2));
      hi = Math.min(hi, Math.max(t1, t2));
      if (lo > hi) return false;
    }
  }
  return lo <= hi;
}
function simplify(points: Point[]): Point[] {
  const result: Point[] = [];
  for (const point of points)
    if (!result.length || distance(point, result[result.length - 1]) > 0.01)
      result.push(point);
  return result;
}
function labelPoint(points: Point[]): Point {
  let remaining =
    points.slice(1).reduce((sum, p, i) => sum + distance(points[i], p), 0) / 2;
  for (let i = 1; i < points.length; i++) {
    const length = distance(points[i - 1], points[i]);
    if (length >= remaining && length > 0) {
      const ratio = remaining / length;
      return {
        x: points[i - 1].x + (points[i].x - points[i - 1].x) * ratio,
        y: points[i - 1].y + (points[i].y - points[i - 1].y) * ratio - 8,
      };
    }
    remaining -= length;
  }
  return points[0];
}
export function routeLink(
  topology: Topology,
  link: Link,
  anchors = portAnchors(topology),
) {
  const p = anchors[link.a.node][link.a.port],
    q = anchors[link.b.node][link.b.port];
  if (topology.optimizeLinks === false) {
    const bend = Math.max(45, distance(p, q) * 0.3);
    return {
      id: link.id,
      d: `M ${p.x} ${p.y} C ${round(p.x + p.dx * bend)} ${round(p.y + p.dy * bend)}, ${round(q.x + q.dx * bend)} ${round(q.y + q.dy * bend)}, ${q.x} ${q.y}`,
      ...labelPoint([p, q]),
      points: [p, q],
    };
  }
  const obstacles = topology.nodes
    .filter((n) => n.id !== link.a.node && n.id !== link.b.node)
    .map((n) => nodeBox(n, 12));
  const clear = (points: Point[]) =>
    points.every(
      (point, i) =>
        !i || !obstacles.some((box) => crossesBox(points[i - 1], point, box)),
    );
  let best: Point[] = [p, q];
  if (!clear(best)) {
    const candidates: Point[][] = [
      [p, { x: q.x, y: p.y }, q],
      [p, { x: p.x, y: q.y }, q],
    ];
    // Bounded candidate search: shortest unobstructed direct / one / two bend route.
    const xs = new Set<number>(),
      ys = new Set<number>();
    for (const box of obstacles) {
      xs.add(box.left);
      xs.add(box.right);
      ys.add(box.top);
      ys.add(box.bottom);
    }
    for (const x of xs) candidates.push([p, { x, y: p.y }, { x, y: q.y }, q]);
    for (const y of ys) candidates.push([p, { x: p.x, y }, { x: q.x, y }, q]);
    let bestLength = Infinity;
    for (const candidate of candidates) {
      const length = candidate
        .slice(1)
        .reduce((sum, point, i) => sum + distance(candidate[i], point), 0);
      if (length < bestLength && clear(candidate)) {
        best = candidate;
        bestLength = length;
      }
    }
  }
  const points = simplify(best);
  return {
    id: link.id,
    d: points
      .map((p, i) => `${i ? "L" : "M"} ${round(p.x)} ${round(p.y)}`)
      .join(" "),
    ...labelPoint(points),
    points,
  };
}

/** Snap nearby rows/columns without rebuilding the user's layout. */
export function alignDevices(topology: Topology): Record<string, Point> {
  const nodes = topology.nodes;
  const positions: Record<string, Point> = Object.fromEntries(
    nodes.map((node) => [node.id, { x: node.x, y: node.y }]),
  );
  for (const axis of ["x", "y"] as const) {
    const sorted = [...nodes].sort(
      (a, b) => a[axis] - b[axis] || a.id.localeCompare(b.id),
    );
    let anchor: number | undefined;
    for (const node of sorted) {
      // Bound the whole group, not just adjacent gaps. Keep an existing anchor
      // so repeated clicks cannot gradually merge rows or columns.
      if (anchor === undefined || node[axis] - anchor > ALIGN_TOLERANCE)
        anchor = node[axis];
      positions[node.id][axis] = anchor;
    }
  }

  // Cancel conflicting moves together, independent of node order. Recheck
  // after restoring positions, since a restored node may block another move.
  const moving = new Set(
    nodes
      .filter((n) => n.x !== positions[n.id].x || n.y !== positions[n.id].y)
      .map((n) => n.id),
  );
  while (moving.size) {
    const blocked = new Set<string>();
    const boxes = nodes.map((node) =>
      nodeBox({ ...node, ...positions[node.id] }),
    );
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        if (!moving.has(nodes[i].id) && !moving.has(nodes[j].id)) continue;
        const a = boxes[i],
          b = boxes[j];
        if (
          a.left < b.right &&
          a.right > b.left &&
          a.top < b.bottom &&
          a.bottom > b.top
        ) {
          if (moving.has(nodes[i].id)) blocked.add(nodes[i].id);
          if (moving.has(nodes[j].id)) blocked.add(nodes[j].id);
        }
      }
    }
    if (!blocked.size) break;
    for (const node of nodes) {
      if (!blocked.has(node.id)) continue;
      positions[node.id] = { x: node.x, y: node.y };
      moving.delete(node.id);
    }
  }
  return positions;
}
