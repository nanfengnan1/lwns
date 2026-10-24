import type { DeviceKind, DeviceTemplate } from "../types/lab";

export const deviceCategories: {
  id: DeviceKind;
  title: string;
  template: string;
  description: string;
}[] = [
  { id: "router", title: "路由器", template: "frr", description: "FRR 路由器" },
  {
    id: "switch",
    title: "交换机",
    template: "linux-bridge",
    description: "交换机（Linux bridge）",
  },
  {
    id: "host",
    title: "PC",
    template: "linux-host",
    description: "PC（Linux / VPCS）",
  },
  {
    id: "firewall",
    title: "防火墙",
    template: "linux-firewall",
    description: "防火墙（Linux）",
  },
];

export function filterDevices(
  catalog: DeviceTemplate[],
  query: string,
  category: string,
) {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return catalog.filter(
    (item) =>
      (category === "all" || item.kind === category) &&
      words.every((word) =>
        `${item.title} ${item.image}`.toLocaleLowerCase().includes(word),
      ),
  );
}
