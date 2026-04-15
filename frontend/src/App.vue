<template>
  <div id="app">
    <a-layout style="min-height: 100vh">
      <a-layout-header style="background: #001529; padding: 0 50px">
        <div style="display: flex; align-items: center; justify-content: space-between; height: 100%">
          <div style="color: white; font-size: 24px; font-weight: bold">
            🌍 HelloAgents智能旅行助手
          </div>
          <a-space>
            <router-link to="/" style="color: white">旅行规划</router-link>
            <router-link to="/db" style="color: white">德铁查询</router-link>
          </a-space>
        </div>
      </a-layout-header>
      <a-layout-content style="padding: 24px">
        <router-view />
      </a-layout-content>
      <a-layout-footer style="text-align: center">
        HelloAgents智能旅行助手 ©2025 基于HelloAgents框架
      </a-layout-footer>
    </a-layout>
  </div>
</template>

<script setup lang="ts">
</script>

<style>
#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', sans-serif;
}
</style>

