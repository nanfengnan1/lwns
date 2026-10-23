import { computed, ref } from "vue";
import { defineStore } from "pinia";

export type SidebarSide = "left" | "right";
export const SIDEBAR_LIMITS = {
  left: { min: 200, max: 420, default: 240 },
  right: { min: 240, max: 480, default: 280 },
};
export const LAYOUT_KEY = "route-ovs-sidebars";
const RAIL = 36;
const STAGE_MIN = 460;

export const useLayoutStore = defineStore("layout", () => {
  const sides = ref({
    left: { width: 240, collapsed: false },
    right: { width: 280, collapsed: false },
  });
  const workspaceWidth = ref(1440);
  const widths = computed(() => {
    const left = sides.value.left,
      right = sides.value.right;
    const result = {
      left: left.collapsed ? RAIL : left.width,
      right: right.collapsed ? RAIL : right.width,
    };
    const leftMin = left.collapsed ? RAIL : SIDEBAR_LIMITS.left.min;
    const rightMin = right.collapsed ? RAIL : SIDEBAR_LIMITS.right.min;
    const excess =
      result.left +
      result.right -
      (Math.max(1000, workspaceWidth.value) - STAGE_MIN);
    if (excess > 0) {
      const slack = result.left + result.right - leftMin - rightMin;
      const reduction = Math.min(excess, slack);
      const leftReduction = Math.round(
        (reduction * (result.left - leftMin)) / slack,
      );
      result.left -= leftReduction;
      result.right -= reduction - leftReduction;
    }
    return result;
  });
  function maxWidth(side: SidebarSide) {
    const other = side === "left" ? "right" : "left";
    return Math.max(
      SIDEBAR_LIMITS[side].min,
      Math.min(
        SIDEBAR_LIMITS[side].max,
        Math.max(1000, workspaceWidth.value) - STAGE_MIN - widths.value[other],
      ),
    );
  }
  function persist() {
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(sides.value));
    } catch {
      /* Layout remains usable with browser storage disabled. */
    }
  }
  function restore() {
    try {
      const data = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "null");
      for (const side of ["left", "right"] as const) {
        const value = data?.[side];
        if (typeof value?.width === "number" && Number.isFinite(value.width))
          sides.value[side].width = Math.round(
            Math.max(
              SIDEBAR_LIMITS[side].min,
              Math.min(SIDEBAR_LIMITS[side].max, value.width),
            ),
          );
        if (typeof value?.collapsed === "boolean")
          sides.value[side].collapsed = value.collapsed;
      }
    } catch {
      /* Invalid or unavailable preferences use the defaults. */
    }
  }
  function setWidth(side: SidebarSide, value: number) {
    if (!Number.isFinite(value)) return;
    sides.value[side].width = Math.round(
      Math.max(SIDEBAR_LIMITS[side].min, Math.min(maxWidth(side), value)),
    );
    persist();
  }
  function toggle(side: SidebarSide) {
    sides.value[side].collapsed = !sides.value[side].collapsed;
    persist();
  }
  function reset(side: SidebarSide) {
    sides.value[side].width = SIDEBAR_LIMITS[side].default;
    persist();
  }
  return {
    sides,
    workspaceWidth,
    widths,
    maxWidth,
    restore,
    setWidth,
    toggle,
    reset,
  };
});
