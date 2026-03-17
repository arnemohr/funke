import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { router } from './router'
import { auth0 } from './plugins/auth0'
import App from './App.vue'
import '@picocss/pico/css/pico.min.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(auth0)
app.mount('#app')
