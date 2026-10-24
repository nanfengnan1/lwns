import { ref, watch } from "vue";

/** Mount on first use, then retain drafts and background task polling. */
export function useRetainedPanel(isOpen: () => boolean) {
  const loaded = ref(false);
  watch(
    isOpen,
    (open) => {
      if (open) loaded.value = true;
    },
    { immediate: true },
  );
  return loaded;
}
