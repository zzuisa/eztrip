<template>
  <div id="app">
    <a-layout style="min-height: 100vh">
      <a-layout-header style="background: #001529; padding: 0 50px">
        <div style="display: flex; align-items: center; justify-content: space-between; height: 100%">
          <div style="color: white; font-size: 24px; font-weight: bold">
            🌍 {{ APP_NAME }}{{ APP_TAGLINE }}
          </div>
          <a-space>
            <router-link to="/" style="color: white">旅行规划</router-link>
            <router-link to="/db" style="color: white">德铁查询</router-link>
            <router-link to="/admin" style="color: white">行程管理</router-link>
          </a-space>
        </div>
      </a-layout-header>
      <a-layout-content style="padding: 24px">
        <router-view v-slot="{ Component }">
          <Transition name="route-shell" mode="out-in">
            <component :is="Component" />
          </Transition>
        </router-view>
      </a-layout-content>
      <a-layout-footer style="text-align: center">
        {{ APP_NAME }}{{ APP_TAGLINE }} ©2025
      </a-layout-footer>
    </a-layout>
  </div>
</template>

<script setup lang="ts">
import { APP_NAME, APP_TAGLINE } from '@/constants/brand'
</script>

<style>
#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', sans-serif;
}

.route-shell-enter-active,
.route-shell-leave-active {
  transition: opacity 560ms cubic-bezier(0.4, 0, 0.2, 1), transform 560ms cubic-bezier(0.4, 0, 0.2, 1);
  will-change: opacity, transform;
}

.route-shell-enter-from,
.route-shell-leave-to {
  opacity: 0;
  transform: translate3d(0, 10px, 0);
}

.route-shell-enter-to,
.route-shell-leave-from {
  opacity: 1;
  transform: translate3d(0, 0, 0);
}

@media (prefers-reduced-motion: reduce) {
  .route-shell-enter-active,
  .route-shell-leave-active {
    transition: none;
  }
}
</style>

