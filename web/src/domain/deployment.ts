import type { Device, Topology } from "../types/lab";

const byId = <T extends { id: string }>(items: T[]) =>
  [...items].sort((a, b) => a.id.localeCompare(b.id));

/** Fields that require replacing a container instead of changing its links. */
export function containerSignature(node: Device) {
  return JSON.stringify([
    node.name,
    node.kind,
    node.template || "",
    node.image,
    node.command,
    node.config,
  ]);
}

/** Layout and annotations never affect the running network. */
export function networkSignature(topology: Topology) {
  return JSON.stringify({
    nodes: byId(topology.nodes).map((node) => ({
      id: node.id,
      container: containerSignature(node),
      ports: [...node.ports]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((port) => [port.name, port.address]),
      gateway: node.gateway,
    })),
    links: byId(topology.links).map(({ id, a, b }) => [
      id,
      a.node,
      a.port,
      b.node,
      b.port,
    ]),
  });
}

export function deploymentChanges(base: Topology, target: Topology) {
  const oldNodes = new Map(base.nodes.map((node) => [node.id, node]));
  const nextNodes = new Map(target.nodes.map((node) => [node.id, node]));
  return {
    added: target.nodes.filter((node) => !oldNodes.has(node.id)),
    removed: base.nodes.filter((node) => !nextNodes.has(node.id)),
    rebuilt: target.nodes.filter((node) => {
      const old = oldNodes.get(node.id);
      return old && containerSignature(old) !== containerSignature(node);
    }),
  };
}
