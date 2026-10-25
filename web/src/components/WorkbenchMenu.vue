<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import { useLayoutStore } from "../stores/layout";
import { useProjectFiles } from "../composables/useProjectFiles";
import DeleteLabButton from "./DeleteLabButton.vue";

type MenuKey = "experiment" | "view" | "tools";
interface MenuAction {
  id: string;
  title: string;
  disabled?: boolean;
  checked?: boolean;
  separator?: boolean;
  hint?: string;
  run: () => unknown;
}
const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore(),
  layout = useLayoutStore();
const files = useProjectFiles();
const root = ref<HTMLElement>(),
  fileInput = ref<HTMLInputElement>();
const open = ref<MenuKey | null>(null),
  focused = ref<MenuKey>("experiment");
const menus: { key: MenuKey; label: string }[] = [
  { key: "experiment", label: "实验" },
  { key: "view", label: "视图" },
  { key: "tools", label: "工具" },
];
const actions = computed<Record<MenuKey, MenuAction[]>>(() => ({
  experiment: [
    {
      id: "new-lab",
      title: "新建项目…",
      disabled: lab.layoutLocked,
      run: () => {
        ui.labDialogMode = "new";
      },
    },
    {
      id: "open-lab",
      title: "打开项目…",
      disabled: lab.layoutLocked,
      run: () => {
        ui.labOpen = true;
      },
    },
    {
      id: "menu-save",
      title: "保存项目",
      disabled: lab.layoutLocked || lab.pendingUpdate,
      run: files.save,
    },
    {
      id: "close-lab",
      title: "关闭项目",
      hint: "关闭当前画布与连接，保留服务器上的项目和运行设备",
      disabled: !lab.canClose,
      run: files.closeProject,
    },
    ...(lab.runtime?.deployment
      ? [
          {
            id: "menu-apply-topology",
            title: "应用拓扑",
            disabled:
              !lab.canUpdate ||
              (!lab.pendingUpdate && !(editor.draftDirty && editor.draft)),
            run: files.applyTopology,
          },
        ]
      : []),
    {
      id: "menu-rename",
      title: "重命名项目…",
      disabled: !lab.canRename,
      run: () => {
        ui.labDialogMode = "rename";
      },
    },
    {
      id: "import",
      title: "导入拓扑 JSON…",
      separator: true,
      disabled: !!lab.operation,
      run: () => fileInput.value?.click(),
    },
    {
      id: "export",
      title: "导出拓扑 JSON",
      disabled: !!lab.operation,
      run: files.exportFile,
    },
  ],
  view: [
    {
      id: "menu-library",
      title: "设备库",
      checked: !layout.sides.left.collapsed,
      run: () => layout.toggle("left"),
    },
    {
      id: "menu-inspector",
      title: "设备属性",
      checked: !layout.sides.right.collapsed,
      run: () => layout.toggle("right"),
    },
    {
      id: "menu-panel",
      title: "底部面板",
      checked: !ui.collapsed,
      run: () => {
        ui.collapsed = !ui.collapsed;
      },
    },
    {
      id: "menu-fit",
      title: "适应画布",
      separator: true,
      run: () => {
        editor.fitRevision++;
      },
    },
    { id: "menu-logs", title: "部署日志", run: () => ui.showPanel("logs") },
    {
      id: "menu-terminals",
      title: "设备终端",
      run: () => ui.showPanel("console"),
    },
  ],
  tools: [
    {
      id: "menu-devices",
      title: "设备管理…",
      run: () => {
        ui.devicesOpen = true;
      },
    },
    {
      id: "menu-images",
      title: "镜像管理（兼容）…",
      run: () => {
        ui.imagesOpen = true;
      },
    },
    {
      id: "menu-environment",
      title: "宿主机环境…",
      run: () => {
        ui.infoOpen = true;
      },
    },
    {
      id: "menu-refresh",
      title: "刷新实验状态",
      disabled: !!lab.operation,
      run: async () => {
        await lab.refresh();
        await lab.refreshEnvironment();
        ui.notify("实验与宿主机状态已刷新");
      },
    },
  ],
}));

function trigger(key: MenuKey) {
  return document.getElementById(`menu-${key}`);
}
function items() {
  return Array.from(
    root.value?.querySelectorAll<HTMLButtonElement>(
      ".menu-popover [role^='menuitem']:not(:disabled)",
    ) || [],
  );
}
function close(restore = false) {
  const active = open.value;
  open.value = null;
  if (restore && active) trigger(active)?.focus();
}
async function show(key: MenuKey, position?: "first" | "last") {
  // Hovering another menu must not leave focus on the body when v-if removes
  // the old menu item. Preserve keyboard navigation inside the new menu.
  const transferFocus = !!document.activeElement?.closest(".menu-popover");
  open.value = key;
  focused.value = key;
  if (position || transferFocus) {
    await nextTick();
    const available = items();
    available[position === "last" ? available.length - 1 : 0]?.focus();
  }
}
function activate(item: MenuAction) {
  if (item.disabled) return;
  close(true);
  void ui.run(item.run);
}
function keyboard(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    close(true);
    return;
  }
  if (event.key === "Tab") {
    close(true);
    return;
  }
  const inPopup = !!(event.target as Element).closest(".menu-popover");
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    const index = menus.findIndex((menu) => menu.key === focused.value);
    const key =
      menus[
        (index + (event.key === "ArrowRight" ? 1 : menus.length - 1)) %
          menus.length
      ]!.key;
    focused.value = key;
    if (open.value) void show(key, inPopup ? "first" : undefined);
    trigger(key)?.focus();
  } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    if (!inPopup) {
      if (event.key === "Home" || event.key === "End") {
        focused.value = menus[event.key === "Home" ? 0 : menus.length - 1]!.key;
        trigger(focused.value)?.focus();
      } else
        void show(focused.value, event.key === "ArrowDown" ? "first" : "last");
      return;
    }
    const available = items(),
      index = available.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? available.length - 1
          : (index + (event.key === "ArrowDown" ? 1 : available.length - 1)) %
            available.length;
    available[next]?.focus();
  }
}
function outside(event: Event) {
  if (open.value && !root.value?.contains(event.target as Node)) close();
}
async function imported(event: Event) {
  const input = event.target as HTMLInputElement,
    file = input.files?.[0];
  input.value = "";
  if (file) await ui.run(() => files.importFile(file));
}
onMounted(() => {
  document.addEventListener("pointerdown", outside);
  document.addEventListener("focusin", outside);
});
watch(
  open,
  (value) => {
    ui.menuOpen = value !== null;
  },
  { flush: "sync" },
);
onBeforeUnmount(() => {
  ui.menuOpen = false;
  document.removeEventListener("pointerdown", outside);
  document.removeEventListener("focusin", outside);
});
</script>

<template>
  <nav
    ref="root"
    class="workbench-menu"
    role="menubar"
    aria-label="工作台菜单"
    @keydown.stop="keyboard"
  >
    <div v-for="menu in menus" :key="menu.key" class="menu-group">
      <button
        :id="`menu-${menu.key}`"
        class="menu-trigger"
        type="button"
        role="menuitem"
        aria-haspopup="menu"
        :aria-expanded="open === menu.key"
        :aria-controls="`popup-${menu.key}`"
        :tabindex="focused === menu.key ? 0 : -1"
        :class="{ active: open === menu.key }"
        @focus="focused = menu.key"
        @click="open === menu.key ? close() : show(menu.key)"
        @mouseenter="open && show(menu.key)"
      >
        {{ menu.label }}<span aria-hidden="true">⌄</span>
      </button>
      <div
        v-if="open === menu.key"
        :id="`popup-${menu.key}`"
        class="menu-popover"
        role="menu"
        :aria-labelledby="`menu-${menu.key}`"
      >
        <template v-for="item in actions[menu.key]" :key="item.id">
          <div
            v-if="item.separator"
            class="menu-separator"
            role="separator"
          ></div>
          <button
            :id="item.id"
            type="button"
            class="menu-action"
            :role="item.checked === undefined ? 'menuitem' : 'menuitemcheckbox'"
            :aria-checked="item.checked"
            tabindex="-1"
            :disabled="item.disabled"
            :title="item.hint"
            @click="activate(item)"
          >
            <span
              v-if="item.checked !== undefined"
              class="menu-check"
              aria-hidden="true"
              >{{ item.checked ? "✓" : "" }}</span
            >
            <span class="menu-action-text">{{ item.title }}</span>
          </button>
        </template>
        <template v-if="menu.key === 'experiment'">
          <div class="menu-separator" role="separator"></div>
          <DeleteLabButton
            id="delete-current-lab"
            class="menu-action menu-delete"
            role="menuitem"
            tabindex="-1"
            @click="close(true)"
            >删除当前项目…</DeleteLabButton
          >
        </template>
      </div>
    </div>
    <input
      id="import-file"
      ref="fileInput"
      type="file"
      accept="application/json,.json"
      hidden
      @change="imported"
    />
  </nav>
</template>

<style scoped>
.workbench-menu {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: 24px;
  margin-right: auto;
  position: relative;
  z-index: 50;
}
.menu-group {
  position: relative;
}
.menu-trigger {
  display: flex;
  gap: 7px;
  align-items: center;
  padding: 8px 11px;
  border: 1px solid transparent;
  color: #d8e3f1;
  background: transparent;
  font-size: 13px;
  border-radius: 6px;
  white-space: nowrap;
}
.menu-trigger > span {
  font-size: 11px;
  color: #a6b8ce;
}
.menu-trigger:hover,
.menu-trigger.active {
  border-color: #ffffff25;
  background: #ffffff13;
  color: #fff;
}
.menu-popover {
  position: absolute;
  top: calc(100% + 12px);
  left: 0;
  width: 224px;
  padding: 6px;
  border: 1px solid #dce4ee;
  background: #fff;
  border-radius: 10px;
  box-shadow:
    0 12px 40px #1426402b,
    0 3px 8px #14264012;
  color: #263950;
}
.menu-action {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  border: 1px solid transparent;
  background: transparent;
  padding: 7px 11px;
  border-radius: 5px;
  text-align: left;
  min-height: 34px;
  color: #31455f;
  font-size: 13px;
}
.menu-action:hover:not(:disabled),
.menu-action:focus-visible {
  background: #edf4ff;
  border-color: transparent;
  color: #1d54a8;
}
.menu-action-text {
  font-weight: 500;
  white-space: nowrap;
}
.menu-separator {
  height: 1px;
  background: #e8edf3;
  margin: 5px 7px;
}
.menu-check {
  width: 14px;
  color: #2866c1;
  flex: none;
}
.menu-delete {
  color: #b55358;
}
@media (max-width: 1200px) {
  .workbench-menu {
    margin-left: 16px;
  }
  .menu-trigger {
    padding-inline: 9px;
  }
}
</style>
