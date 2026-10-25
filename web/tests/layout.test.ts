import { createPinia, setActivePinia } from "pinia";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { LAYOUT_KEY, useLayoutStore } from "../src/stores/layout";

let stored: Map<string, string>;
beforeEach(() => {
  setActivePinia(createPinia());
  stored = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => stored.set(key, value),
  });
});
afterEach(() => vi.unstubAllGlobals());
describe("sidebar layout", () => {
  it("reads legacy layout preferences and writes changes under the new name", () => {
    stored.set(
      "route-ovs-sidebars",
      JSON.stringify({ left: { width: 320, collapsed: true } }),
    );
    const layout = useLayoutStore();
    layout.restore();
    expect(layout.sides.left).toEqual({ width: 320, collapsed: true });
    layout.toggle("left");
    expect(JSON.parse(stored.get("lwns-sidebars")!).left).toEqual({
      width: 320,
      collapsed: false,
    });
    stored.set(
      "route-ovs-sidebars",
      JSON.stringify({ left: { width: 400, collapsed: true } }),
    );
    layout.restore();
    expect(layout.sides.left).toEqual({ width: 320, collapsed: false });
  });
  it("restores independent widths and collapsed states across a reload", () => {
    const layout = useLayoutStore();
    layout.setWidth("left", 350);
    layout.setWidth("right", 400);
    layout.toggle("left");
    setActivePinia(createPinia());
    const restored = useLayoutStore();
    restored.restore();
    expect(restored.widths).toEqual({ left: 36, right: 400 });
    restored.toggle("left");
    expect(restored.widths.left).toBe(350);
  });
  it("reserves canvas space at narrow widths and restores preferred widths when widened", () => {
    const layout = useLayoutStore();
    layout.setWidth("left", 420);
    layout.setWidth("right", 480);
    layout.workspaceWidth = 1000;
    expect(layout.widths.left).toBeGreaterThanOrEqual(200);
    expect(layout.widths.right).toBeGreaterThanOrEqual(240);
    expect(layout.widths.left + layout.widths.right).toBeLessThanOrEqual(540);
    layout.workspaceWidth = 1440;
    expect(layout.widths).toEqual({ left: 420, right: 480 });
  });
  it("clamps dragging to available space and uses space freed by a collapsed sidebar", () => {
    const layout = useLayoutStore();
    layout.workspaceWidth = 1000;
    layout.setWidth("left", 900);
    expect(layout.widths.left).toBe(260);
    layout.toggle("right");
    layout.setWidth("left", 900);
    expect(layout.widths.left).toBe(420);
    layout.setWidth("right", -10);
    layout.toggle("right");
    expect(layout.widths.left + layout.widths.right).toBeLessThanOrEqual(540);
  });
  it("resets only the requested side", () => {
    const layout = useLayoutStore();
    layout.setWidth("left", 380);
    layout.setWidth("right", 400);
    layout.reset("left");
    expect(layout.widths).toEqual({ left: 240, right: 400 });
  });
  it("rejects malformed storage and clamps valid numeric preferences", () => {
    const layout = useLayoutStore();
    stored.set(LAYOUT_KEY, "{broken");
    expect(() => layout.restore()).not.toThrow();
    stored.set(
      LAYOUT_KEY,
      JSON.stringify({
        left: { width: 9999, collapsed: "false" },
        right: { width: "NaN", collapsed: true },
      }),
    );
    layout.restore();
    expect(layout.sides).toEqual({
      left: { width: 420, collapsed: false },
      right: { width: 280, collapsed: true },
    });
    layout.setWidth("left", NaN);
    expect(layout.sides.left.width).toBe(420);
  });
  it("remains usable when localStorage access fails", () => {
    vi.stubGlobal("localStorage", {
      getItem() {
        throw Error("blocked");
      },
      setItem() {
        throw Error("blocked");
      },
    });
    const layout = useLayoutStore();
    layout.restore();
    layout.setWidth("left", 300);
    layout.toggle("right");
    expect(layout.widths).toEqual({ left: 300, right: 36 });
  });
});
