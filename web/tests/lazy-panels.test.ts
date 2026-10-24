import { effectScope, nextTick, ref } from "vue";
import { describe, expect, it } from "vitest";
import { useRetainedPanel } from "../src/composables/useRetainedPanel";

describe("lazy management panels", () => {
  it("mounts only on first use and retains background work when closed", async () => {
    const scope = effectScope(),
      open = ref(false);
    const loaded = scope.run(() => useRetainedPanel(() => open.value))!;
    expect(loaded.value).toBe(false);
    open.value = true;
    await nextTick();
    expect(loaded.value).toBe(true);
    open.value = false;
    await nextTick();
    expect(loaded.value).toBe(true);
    scope.stop();
  });

  it("loads a panel that is already open when its owner mounts", () => {
    const scope = effectScope();
    expect(scope.run(() => useRetainedPanel(() => true))!.value).toBe(true);
    scope.stop();
  });
});
