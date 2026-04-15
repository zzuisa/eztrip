import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import 'mapbox-gl/dist/mapbox-gl.css'
import App from './App.vue'
import Home from './views/Home.vue'
import Result from './views/Result.vue'
import DbTrainHome from './views/DbTrainHome.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'Home',
      component: Home
    },
    {
      path: '/result',
      name: 'Result',
      component: Result
    },
    {
      path: '/db',
      name: 'DbTrainHome',
      component: DbTrainHome
    }
  ]
})

const app = createApp(App)

app.use(router)
app.use(Antd)

app.mount('#app')

