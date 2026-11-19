<template>
  <a-card v-if="weatherInfo?.length > 0" id="weather" title="天气信息" :bordered="false" class="weather-section-card">
    <a-list :data-source="weatherInfo" :grid="{ gutter: 16, column: 3 }">
      <template #renderItem="{ item }">
        <a-list-item>
          <a-card size="small" class="weather-card">
            <div class="weather-date">{{ item.date }}</div>
            <div class="weather-info-row">
              <span class="weather-icon">☀️</span>
              <div>
                <div class="weather-label">白天</div>
                <div class="weather-value">{{ item.day_weather }} {{ item.day_temp }}°C</div>
              </div>
            </div>
            <div class="weather-info-row">
              <span class="weather-icon">🌙</span>
              <div>
                <div class="weather-label">夜间</div>
                <div class="weather-value">{{ item.night_weather }} {{ item.night_temp }}°C</div>
              </div>
            </div>
            <div class="weather-wind">
              💨 {{ item.wind_direction }} {{ item.wind_power }}
            </div>
          </a-card>
        </a-list-item>
      </template>
    </a-list>
  </a-card>
</template>

<script setup lang="ts">
defineProps<{ weatherInfo: any[] }>()
</script>
