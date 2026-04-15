<template>
  <article class="landing">
    <div class="landing-mark">⚓</div>
    <h2>Funke</h2>
    <p class="tagline">Verein für mobile Machenschaften e.V.</p>
    <router-link to="/login">
      <button class="outline">Admin-Bereich</button>
    </router-link>
  </article>
</template>

<style scoped>
.landing {
  text-align: center;
  padding: 4rem 2rem;
  max-width: 480px;
  margin: 2rem auto;
}

.landing-mark {
  font-size: 3rem;
  margin-bottom: 0.5rem;
}

.landing h2 {
  color: var(--color-brand, #0C1E3C);
  margin-bottom: 0.25rem;
  font-size: 2rem;
  letter-spacing: 0.02em;
}

.tagline {
  color: var(--color-text-muted, #5C6470);
  font-size: var(--text-base);
  margin-bottom: 2rem;
}

</style>
