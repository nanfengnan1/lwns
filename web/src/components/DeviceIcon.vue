<script setup lang="ts">
import type { DeviceKind } from "../types/lab";
defineProps<{ kind: DeviceKind }>();
</script>

<template>
  <svg
    viewBox="0 0 32 32"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="kind === 'router'">
      <circle cx="16" cy="16" r="12" />
      <path
        d="M8 16h16M16 8v16M8 16l3-3m-3 3 3 3m13-3-3-3m3 3-3 3M16 8l-3 3m3-3 3 3m-3 13-3-3m3 3 3-3"
      />
    </template>
    <template v-else-if="kind === 'switch'">
      <rect x="3" y="8" width="26" height="16" rx="3" />
      <path d="M7 18v3m4-3v3m4-3v3m4-3v3m4-3v3m4-3v3M7 12h8m8 0h2" />
    </template>
    <template v-else-if="kind === 'firewall'">
      <path d="M16 3 28 8v8c0 6-6 11-12 13C10 27 4 22 4 16V8Z" />
      <path d="M8 12h16M8 18h16M12 8v4m8 0v6m-8 0v6" />
    </template>
    <template v-else>
      <rect x="4" y="5" width="24" height="17" rx="2" />
      <path d="M12 27h8m-4-5v5M8 18h16" />
    </template>
  </svg>
</template>
