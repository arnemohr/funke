<template>
  <article>
    <div aria-busy="true">
      Completing sign in...
    </div>
  </article>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuth0 } from '@auth0/auth0-vue'
import { useRouter } from 'vue-router'

const { isAuthenticated, isLoading, handleRedirectCallback } = useAuth0()
const router = useRouter()

onMounted(async () => {
  // Wait for Auth0 to finish loading
  const checkAuth = setInterval(() => {
    if (!isLoading.value) {
      clearInterval(checkAuth)
      if (isAuthenticated.value) {
        router.push('/admin/events')
      } else {
        router.push('/login')
      }
    }
  }, 100)
})
</script>

<style scoped>
article {
  max-width: 400px;
  margin: 2rem auto;
  text-align: center;
  padding: 2rem;
}
</style>
