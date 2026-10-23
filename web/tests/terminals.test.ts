import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { beforeEach, expect, it } from "vitest";
import example from "../../examples/basic-lab.json";
import { parseTopology } from "../src/domain/topology";
import { useLabStore } from "../src/stores/lab";
import { useTerminalsStore } from "../src/stores/terminals";

beforeEach(() => setActivePinia(createPinia()));
async function setup() {
  const lab = useLabStore();
  lab.adopt(parseTopology(example));
  lab.environment.ready = true;
  lab.runtime = {
    phase: "running",
    deployment: "test",
    logs: [],
    nodes: {
      r1: { id: "router", name: "R1", pid: 1 },
      pc1: { id: "host", name: "PC1", pid: 2 },
    },
  };
  const terminals = useTerminalsStore();
  await nextTick();
  return { lab, terminals };
}
it("reuses a device tab while keeping the router shell separate", async () => {
  const { terminals } = await setup();
  terminals.open("r1");
  const first = terminals.active;
  terminals.open("pc1");
  terminals.open("r1");
  expect(terminals.active).toBe(first);
  expect(terminals.tabs).toHaveLength(2);
  terminals.open("r1", "shell");
  expect(terminals.tabs).toHaveLength(3);
  terminals.close(terminals.active);
  expect(terminals.tabs).toHaveLength(2);
  expect(terminals.active).toBe(terminals.tabs[1]!.id);
});
it("closes old sessions on redeployment and document changes", async () => {
  const { lab, terminals } = await setup();
  terminals.open("r1");
  lab.runtime!.deployment = "replacement";
  await nextTick();
  expect(terminals.tabs).toHaveLength(0);
  terminals.open("pc1");
  lab.newLab();
  await nextTick();
  expect(terminals.tabs).toHaveLength(0);
  expect(terminals.active).toBe("");
});
it("refuses undeployed devices and closes tabs when cleanup starts", async () => {
  const { lab, terminals } = await setup();
  expect(() => terminals.open("pc2")).toThrow("部署");
  terminals.open("r1");
  lab.runtime!.phase = "destroying";
  await nextTick();
  expect(terminals.tabs).toHaveLength(0);
});
