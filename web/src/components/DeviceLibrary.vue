<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import DeviceIcon from "./DeviceIcon.vue";
import { deviceCategories } from "../domain/library";
import { colors } from "../domain/topology";
import type { DeviceKind } from "../types/lab";

const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
const selected = ref<DeviceKind | null>(null);
const visibleCount = ref(60);
const list = ref<HTMLElement>();
const categoryButtons = ref<HTMLButtonElement[]>([]);
const groups = computed(() =>
  deviceCategories.map((category) => ({
    ...category,
    count: lab.catalog.filter((item) => item.kind === category.id).length,
  })),
);
const current = computed(() =>
  groups.value.find((group) => group.id === selected.value),
);
const devices = computed(() =>
  lab.catalog.filter((item) => item.kind === selected.value),
);

watch(selected, async () => {
  visibleCount.value = 60;
  await nextTick();
  if (list.value) list.value.scrollTop = 0;
});
function enter(kind: DeviceKind | null) {
  selected.value = kind;
}
function navigate(event: KeyboardEvent, index: number) {
  const last = groups.value.length - 1;
  const next =
    event.key === "ArrowRight"
      ? (index + 1) % groups.value.length
      : event.key === "ArrowLeft"
        ? (index + last) % groups.value.length
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? last
            : null;
  if (next === null) return;
  event.preventDefault();
  categoryButtons.value[next]?.focus();
  enter(groups.value[next]!.id);
}
function back() {
  const index = groups.value.findIndex((group) => group.id === selected.value);
  enter(null);
  categoryButtons.value[index]?.focus();
}
function drag(event: DragEvent, kind: string) {
  if (event.dataTransfer) {
    event.dataTransfer.setData("text/plain", kind);
    event.dataTransfer.effectAllowed = "copy";
  }
}
</script>

<template>
  <aside class="library">
    <div class="library-heading">
      <h2>设备库</h2>
      <span>{{ lab.catalog.length }} 个设备</span>
    </div>
    <nav class="device-category-nav" aria-label="设备分类">
      <button
        v-for="(group, index) in groups"
        :key="group.id"
        ref="categoryButtons"
        class="category-tile"
        :class="[group.id, { active: selected === group.id }]"
        :style="{ '--device-color': colors[group.id] }"
        :data-category="group.id"
        :aria-pressed="selected === group.id"
        :aria-label="`${group.title}，${group.count} 个设备`"
        @click="enter(group.id)"
        @keydown="navigate($event, index)"
      >
        <span class="category-symbol"><DeviceIcon :kind="group.id" /></span>
        <b>{{ group.title }}</b
        ><span class="category-count">{{ group.count }}</span>
      </button>
    </nav>
    <template v-if="current">
      <div class="library-breadcrumb">
        <button
          id="library-back"
          title="返回设备分类"
          aria-label="返回设备分类"
          @click="back"
        >
          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="m11 5-5 5 5 5M6 10h10" />
          </svg>
        </button>
        <b>{{ current.title }}</b
        ><span>{{ current.count }} 个设备</span>
      </div>
      <div
        id="device-library"
        ref="list"
        class="device-library-scroll"
        tabindex="0"
        :aria-label="`${current.title}设备列表`"
      >
        <section
          class="device-category"
          :data-device-group="current.id"
          :aria-label="current.title"
        >
          <div :id="`device-group-${current.id}`" class="device-group-items">
            <button
              v-for="item in devices.slice(0, visibleCount)"
              :key="item.id || item.kind"
              class="device-card"
              :class="item.kind"
              :style="{ '--device-color': colors[item.kind] }"
              :data-kind="item.kind"
              :data-template="item.id || item.kind"
              :data-image="item.image"
              :title="item.title + '\n' + item.image + '\n点击添加，或拖入画布'"
              :draggable="!lab.locked"
              :disabled="lab.locked"
              @dragstart="drag($event, item.id || item.kind)"
              @click="ui.run(() => editor.addNode(item.id || item.kind))"
            >
              <span class="device-icon"><DeviceIcon :kind="item.kind" /></span>
              <span class="device-card-label"
                ><b>{{ item.title }}</b
                ><small>{{ item.image }}</small></span
              >
              <span v-if="item.present === false" class="device-unavailable"
                >未加载</span
              >
            </button>
          </div>
          <div v-if="!devices.length" class="library-empty">
            <DeviceIcon :kind="current.id" />
            <b>此分类暂无设备</b>
            <p>通过顶部「工具 → 镜像管理」添加。</p>
          </div>
          <button
            v-if="devices.length > visibleCount"
            class="library-more"
            @click="visibleCount += 60"
          >
            显示更多 · 剩余 {{ devices.length - visibleCount }}
          </button>
        </section>
      </div>
    </template>
    <div v-else id="library-home" class="library-home">
      <svg viewBox="0 0 72 64" fill="none" aria-hidden="true">
        <circle cx="18.5" cy="17" r="11" />
        <circle cx="53.5" cy="17" r="11" />
        <circle cx="18.5" cy="47" r="11" />
        <circle cx="53.5" cy="47" r="11" />
        <path d="M14 17h9m-4.5-4.5v9M49 17h9M14 47h9m35-4.5-9 9m0-9 9 9" />
      </svg>
      <b>选择设备类别</b>
      <p>进入分类，浏览可用设备</p>
    </div>
  </aside>
</template>
