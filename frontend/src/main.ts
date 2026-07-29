import { createApp } from 'vue'
// 全项目仅使用 ElMessage 函数式组件，按需引入样式，避免全量注册
// Element Plus（约 1MB JS + 350KB CSS）拖慢首屏
import 'element-plus/es/components/message/style/css'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(router)
app.mount('#app')
