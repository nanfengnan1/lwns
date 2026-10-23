import type { DeviceTemplate } from "../types/lab";

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
        `${item.title} ${item.image} ${item.id || ""}`
          .toLocaleLowerCase()
          .includes(word),
      ),
  );
}
