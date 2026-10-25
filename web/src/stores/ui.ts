import { defineStore } from "pinia";
import { ref } from "vue";
import { ApiError } from "../api/client";

export const useUiStore = defineStore("ui", () => {
  const notification = ref<{ message: string; error: boolean } | null>(null);
  const accessOpen = ref(false),
    infoOpen = ref(false);
  const imagesOpen = ref(false);
  const labDialogMode = ref<"new" | "rename" | null>(null);
  const labOpen = ref(false);
  const menuOpen = ref(false);
  const captureOpen = ref(false),
    captureLink = ref("");
  const panel = ref<"logs" | "console">("logs"),
    collapsed = ref(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  function notify(message: string, error = false) {
    notification.value = { message, error };
    clearTimeout(timer);
    timer = setTimeout(
      () => {
        notification.value = null;
      },
      error ? 9000 : 3500,
    );
  }
  function report(error: unknown) {
    if (error instanceof ApiError && error.status === 401)
      accessOpen.value = true;
    notify(error instanceof Error ? error.message : String(error), true);
  }
  async function run(action: () => unknown | Promise<unknown>) {
    try {
      await action();
    } catch (error) {
      report(error);
    }
  }
  function showPanel(value: "logs" | "console") {
    panel.value = value;
    collapsed.value = false;
  }
  return {
    notification,
    accessOpen,
    infoOpen,
    imagesOpen,
    labDialogMode,
    labOpen,
    menuOpen,
    captureOpen,
    captureLink,
    panel,
    collapsed,
    notify,
    report,
    run,
    showPanel,
  };
});
