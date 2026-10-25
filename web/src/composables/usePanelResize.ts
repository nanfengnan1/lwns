import { computed, onBeforeUnmount, onMounted, ref, type Ref } from "vue";

const STORAGE_KEY = "lwns-panel-height";
const DEFAULT_HEIGHT = 174;
const MIN_HEIGHT = 96;

/** Keeps the output panel inside the stage while reserving space for the canvas. */
export function usePanelResize(panel: Ref<HTMLElement | undefined>) {
  const preferredHeight = ref(DEFAULT_HEIGHT);
  const maxHeight = ref(DEFAULT_HEIGHT);
  const resizing = ref(false);
  const height = computed(() =>
    Math.round(
      Math.min(maxHeight.value, Math.max(MIN_HEIGHT, preferredHeight.value)),
    ),
  );
  let observer: ResizeObserver | undefined;
  let drag: {
    pointer: number;
    y: number;
    height: number;
    handle: HTMLElement;
  } | null = null;

  function measure() {
    const root = panel.value,
      stage = root?.parentElement;
    const canvas = stage?.querySelector<HTMLElement>(".canvas-wrap");
    // The layout tools and save/deploy buttons share one row inside this
    // toolbar. Count its outer height once, including its horizontal scrollbar.
    const toolbarHeight =
      stage?.querySelector<HTMLElement>(".lab-toolbar")?.offsetHeight ?? 0;
    const tabs = root?.querySelector<HTMLElement>(".panel-tabs");
    const handle = root?.querySelector<HTMLElement>(".panel-resize-handle");
    if (!root || !stage || !canvas || !tabs || !handle) return;
    const chrome =
      tabs.offsetHeight +
      parseFloat(getComputedStyle(handle).height) +
      parseFloat(getComputedStyle(root).borderTopWidth);
    const canvasStyle = getComputedStyle(canvas);
    const canvasMinimum =
      (parseFloat(canvasStyle.minHeight) || 280) +
      (parseFloat(canvasStyle.marginTop) || 0) +
      (parseFloat(canvasStyle.marginBottom) || 0);
    maxHeight.value = Math.max(
      MIN_HEIGHT,
      Math.floor(stage.clientHeight - toolbarHeight - canvasMinimum - chrome),
    );
  }
  function persist() {
    try {
      localStorage.setItem(STORAGE_KEY, String(preferredHeight.value));
    } catch {
      /* Resizing still works when browser storage is unavailable. */
    }
  }
  function beginResize(event: PointerEvent) {
    if (event.button !== 0 || drag) return;
    event.preventDefault();
    const handle = event.currentTarget as HTMLElement;
    measure();
    drag = {
      pointer: event.pointerId,
      y: event.clientY,
      height: height.value,
      handle,
    };
    handle.setPointerCapture(event.pointerId);
    handle.focus({ preventScroll: true });
    resizing.value = true;
    document.documentElement.classList.add("resizing-panel");
  }
  function resize(event: PointerEvent) {
    if (!drag || event.pointerId !== drag.pointer) return;
    preferredHeight.value = Math.max(
      MIN_HEIGHT,
      Math.min(maxHeight.value, drag.height + drag.y - event.clientY),
    );
  }
  function endResize() {
    const active = drag;
    drag = null;
    resizing.value = false;
    document.documentElement.classList.remove("resizing-panel");
    if (active?.handle.hasPointerCapture(active.pointer))
      active.handle.releasePointerCapture(active.pointer);
    if (active) persist();
  }
  function resetHeight() {
    preferredHeight.value = DEFAULT_HEIGHT;
    persist();
  }
  function keyResize(event: KeyboardEvent) {
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    // ResizeObserver can run after a key event when the viewport has just
    // changed. Refresh the limit before using End or adjusting the height.
    measure();
    const values: Record<string, number> = {
      ArrowUp: height.value + 24,
      ArrowDown: height.value - 24,
      Home: MIN_HEIGHT,
      End: maxHeight.value,
    };
    const next = values[event.key];
    if (next === undefined) return;
    event.preventDefault();
    preferredHeight.value = Math.max(
      MIN_HEIGHT,
      Math.min(maxHeight.value, next),
    );
    persist();
  }
  onMounted(() => {
    try {
      const stored = Number(
        localStorage.getItem(STORAGE_KEY) ??
          localStorage.getItem("route-ovs-panel-height"),
      );
      if (Number.isFinite(stored) && stored >= MIN_HEIGHT)
        preferredHeight.value = stored;
    } catch {
      /* Use the default height. */
    }
    measure();
    observer = new ResizeObserver(measure);
    const stage = panel.value?.parentElement;
    if (stage) {
      observer.observe(stage);
      // A title or scrollbar can change the toolbar without resizing the stage.
      // Observing the outer toolbar also covers changes in its nested controls.
      stage
        .querySelectorAll(".lab-toolbar")
        .forEach((toolbar) => observer!.observe(toolbar));
    }
  });
  onBeforeUnmount(() => {
    endResize();
    observer?.disconnect();
  });
  return {
    height,
    maxHeight,
    minHeight: MIN_HEIGHT,
    resizing,
    beginResize,
    resize,
    endResize,
    resetHeight,
    keyResize,
  };
}
