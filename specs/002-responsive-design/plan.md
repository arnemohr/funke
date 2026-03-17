# Implementation Plan: Responsive Design

## Overview

Transform the Funke Event Management frontend into a fully responsive application that works seamlessly across mobile, tablet, and desktop devices.

**Reference**: See `docs/RESPONSIVE_DESIGN_SPEC.md` for detailed specifications.

---

## Phase 1: Foundation & Critical Fixes

### Task 1.1: Create Global Responsive Utilities

**File**: `frontend/src/assets/styles/responsive.css` (new)

**Actions**:
1. Create CSS custom properties for breakpoints
2. Define spacing scale variables
3. Define typography scale with `clamp()`
4. Create utility classes for responsive visibility

**Code**:
```css
:root {
  /* Breakpoints */
  --breakpoint-sm: 576px;
  --breakpoint-md: 768px;
  --breakpoint-lg: 1024px;
  --breakpoint-xl: 1280px;

  /* Spacing Scale */
  --space-xs: 0.25rem;
  --space-sm: 0.5rem;
  --space-md: 1rem;
  --space-lg: 1.5rem;
  --space-xl: 2rem;
  --space-2xl: 3rem;

  /* Fluid Typography */
  --font-size-base: clamp(0.875rem, 0.8rem + 0.4vw, 1rem);
  --font-size-h1: clamp(1.5rem, 1.2rem + 1.5vw, 2.5rem);
  --font-size-h2: clamp(1.25rem, 1rem + 1.25vw, 2rem);
  --font-size-h3: clamp(1.1rem, 0.9rem + 1vw, 1.5rem);
  --font-size-small: clamp(0.75rem, 0.7rem + 0.25vw, 0.875rem);

  /* Touch Targets */
  --touch-target-min: 44px;
}

/* Responsive visibility utilities */
@media (max-width: 575px) {
  .hide-mobile { display: none !important; }
}

@media (min-width: 576px) and (max-width: 767px) {
  .hide-tablet-portrait { display: none !important; }
}

@media (min-width: 768px) {
  .hide-tablet-up { display: none !important; }
}

@media (max-width: 767px) {
  .show-tablet-up { display: none !important; }
}
```

**Estimated Effort**: Small

---

### Task 1.2: Import Global Styles

**File**: `frontend/src/main.js`

**Actions**:
1. Import the new responsive.css after Pico CSS

**Code Change**:
```javascript
import '@picocss/pico/css/pico.min.css'
import './assets/styles/responsive.css'  // Add this line
```

**Estimated Effort**: Trivial

---

### Task 1.3: Fix Form Layouts (EventsPage)

**File**: `frontend/src/pages/admin/EventsPage.vue`

**Actions**:
1. Update `.form-row` to stack on mobile
2. Ensure form inputs are touch-friendly

**Current Code** (line ~1179):
```css
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
```

**New Code**:
```css
.form-row {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1fr;
}

@media (min-width: 768px) {
  .form-row {
    grid-template-columns: 1fr 1fr;
  }
}

/* Touch-friendly inputs on mobile */
@media (max-width: 767px) {
  .form-row input,
  .form-row select,
  .form-row textarea {
    min-height: var(--touch-target-min, 44px);
    font-size: 16px; /* Prevents iOS zoom */
  }
}
```

**Estimated Effort**: Small

---

### Task 1.4: Modal Responsiveness (EventsPage)

**File**: `frontend/src/pages/admin/EventsPage.vue`

**Actions**:
1. Make modals full-width on mobile
2. Stack modal footer buttons on mobile
3. Ensure modals are scrollable

**Current Code** (line ~1163):
```css
dialog article {
  max-width: 600px;
}

dialog article.modal-wide {
  max-width: 750px;
}
```

**New Code**:
```css
dialog article {
  max-width: 600px;
  margin: 1rem;
}

dialog article.modal-wide {
  max-width: 750px;
}

@media (max-width: 767px) {
  dialog article,
  dialog article.modal-wide {
    max-width: calc(100% - 1rem);
    margin: 0.5rem;
    max-height: calc(100vh - 1rem);
    overflow-y: auto;
  }

  dialog footer {
    flex-direction: column;
  }

  dialog footer button {
    width: 100%;
    margin: 0;
  }

  dialog footer .modal-actions {
    width: 100%;
  }

  dialog footer .modal-actions button {
    flex: 1;
  }
}
```

**Estimated Effort**: Small

---

### Task 1.5: Table Horizontal Scroll (EventsPage)

**File**: `frontend/src/pages/admin/EventsPage.vue`

**Actions**:
1. Wrap table in scrollable container
2. Add scroll indicator shadow

**Template Change** (around line 71):
```html
<!-- Before -->
<table v-else>

<!-- After -->
<div class="table-container">
  <table v-else>
    ...
  </table>
</div>
```

**CSS Addition**:
```css
.table-container {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 0 -1rem;
  padding: 0 1rem;
}

@media (min-width: 768px) {
  .table-container {
    margin: 0;
    padding: 0;
    overflow-x: visible;
  }
}
```

**Estimated Effort**: Small

---

### Task 1.6: Touch-Friendly Buttons

**File**: `frontend/src/assets/styles/responsive.css`

**Actions**:
1. Add global touch target sizing
2. Ensure adequate spacing between interactive elements

**Code Addition**:
```css
/* Touch-friendly interactive elements */
@media (max-width: 767px) {
  button:not(.tiny):not(.small),
  [role="button"],
  a.button {
    min-height: var(--touch-target-min);
    padding: 0.75rem 1rem;
  }

  /* Ensure spacing between clickable items */
  .actions-cell,
  .button-group,
  .modal-actions {
    gap: 0.5rem;
  }
}
```

**Estimated Effort**: Small

---

### Task 1.7: Page Header Responsiveness

**File**: `frontend/src/pages/admin/EventsPage.vue`

**Actions**:
1. Stack header on mobile (title + button)

**Current Code** (line ~1084):
```css
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}
```

**New Code**:
```css
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

@media (max-width: 575px) {
  header {
    flex-direction: column;
    align-items: stretch;
  }

  header button {
    width: 100%;
  }
}
```

**Estimated Effort**: Trivial

---

## Phase 2: Enhanced Mobile Experience

### Task 2.1: DebugPage Table-to-Card Transformation

**File**: `frontend/src/pages/admin/DebugPage.vue`

**Actions**:
1. Add `data-label` attributes to table cells
2. Transform table to cards on mobile via CSS

**Template Changes** (update each `<td>`):
```html
<td data-label="Name">{{ reg.name }}</td>
<td data-label="E-Mail" class="mono">
  <a :href="`mailto:${reg.email}`">{{ reg.email }}</a>
</td>
<td data-label="Kontakt" class="contact-cell">...</td>
<td data-label="Personen">{{ reg.group_size }}</td>
<td data-label="Status">...</td>
<!-- etc. -->
```

**CSS Addition**:
```css
@media (max-width: 767px) {
  .registrations-table {
    border: none;
  }

  .registrations-table thead {
    display: none;
  }

  .registrations-table tbody {
    display: block;
  }

  .registrations-table tr {
    display: block;
    padding: 0.75rem;
    margin-bottom: 0.5rem;
    border: 1px solid var(--pico-muted-border-color, #e2e8f0);
    border-radius: var(--pico-border-radius);
    background: white;
  }

  .registrations-table td {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.35rem 0;
    border: none;
    text-align: right;
  }

  .registrations-table td::before {
    content: attr(data-label);
    font-weight: 600;
    text-align: left;
    color: #64748b;
    font-size: 0.7rem;
    text-transform: uppercase;
  }

  .registrations-table td:last-child {
    border-bottom: none;
  }

  /* Hide less important columns on mobile */
  .registrations-table td[data-label="Angemeldet"],
  .registrations-table td[data-label="Beantwortet"],
  .registrations-table td[data-label="Nachger."],
  .registrations-table td[data-label="Notizen"] {
    display: none;
  }
}
```

**Estimated Effort**: Medium

---

### Task 2.2: Navigation Hamburger Menu

**File**: `frontend/src/App.vue`

**Actions**:
1. Add hamburger menu icon
2. Create slide-out mobile menu
3. Toggle menu on click
4. Close on outside click

**Template Changes**:
```html
<nav class="container-fluid">
  <ul>
    <li><strong>Funke</strong></li>
  </ul>

  <!-- Desktop nav -->
  <ul class="desktop-nav">
    <template v-if="isAuthenticated">
      <li><router-link to="/admin/events">Veranstaltungen</router-link></li>
      <li><router-link to="/admin/debug">Debug</router-link></li>
      <li><a href="#" @click.prevent="logout">Abmelden</a></li>
    </template>
    <template v-else>
      <li><router-link to="/login">Anmelden</router-link></li>
    </template>
  </ul>

  <!-- Mobile hamburger -->
  <button class="hamburger" @click="mobileMenuOpen = !mobileMenuOpen" aria-label="Menu">
    <span></span>
    <span></span>
    <span></span>
  </button>

  <!-- Mobile menu overlay -->
  <div class="mobile-menu-overlay" :class="{ open: mobileMenuOpen }" @click="mobileMenuOpen = false">
    <div class="mobile-menu" @click.stop>
      <template v-if="isAuthenticated">
        <router-link to="/admin/events" @click="mobileMenuOpen = false">Veranstaltungen</router-link>
        <router-link to="/admin/debug" @click="mobileMenuOpen = false">Debug</router-link>
        <a href="#" @click.prevent="logout; mobileMenuOpen = false">Abmelden</a>
      </template>
      <template v-else>
        <router-link to="/login" @click="mobileMenuOpen = false">Anmelden</router-link>
      </template>
    </div>
  </div>
</nav>
```

**Script Addition**:
```javascript
const mobileMenuOpen = ref(false)
```

**CSS Addition**:
```css
.hamburger {
  display: none;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  width: 44px;
  height: 44px;
  padding: 10px;
  background: transparent;
  border: none;
  cursor: pointer;
}

.hamburger span {
  display: block;
  width: 24px;
  height: 2px;
  background: var(--pico-color);
  transition: transform 0.2s;
}

.desktop-nav {
  display: flex;
}

.mobile-menu-overlay {
  display: none;
}

@media (max-width: 767px) {
  .desktop-nav {
    display: none;
  }

  .hamburger {
    display: flex;
  }

  .mobile-menu-overlay {
    display: block;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.2s, visibility 0.2s;
    z-index: 100;
  }

  .mobile-menu-overlay.open {
    opacity: 1;
    visibility: visible;
  }

  .mobile-menu {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: 280px;
    max-width: 80vw;
    background: white;
    padding: 1rem;
    transform: translateX(100%);
    transition: transform 0.2s;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .mobile-menu-overlay.open .mobile-menu {
    transform: translateX(0);
  }

  .mobile-menu a {
    display: block;
    padding: 0.75rem 1rem;
    border-radius: var(--pico-border-radius);
    text-decoration: none;
  }

  .mobile-menu a:hover {
    background: #f1f5f9;
  }
}
```

**Estimated Effort**: Medium

---

### Task 2.3: Event Info Summary Responsiveness

**File**: `frontend/src/pages/admin/EventsPage.vue`

**Actions**:
1. Stack labels and values on mobile

**CSS Changes**:
```css
.event-info-row {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  margin-bottom: 0.5rem;
}

@media (min-width: 576px) {
  .event-info-row {
    flex-direction: row;
    gap: 0.5rem;
    margin-bottom: 0.25rem;
  }

  .event-info-label {
    min-width: 120px;
  }
}
```

**Estimated Effort**: Trivial

---

### Task 2.4: Filter Tabs Horizontal Scroll

**File**: `frontend/src/pages/admin/EventsPage.vue`

**Actions**:
1. Make filter tabs scrollable on mobile

**CSS Changes**:
```css
nav ul {
  list-style: none;
  padding: 0;
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 0.5rem;
}

nav ul::-webkit-scrollbar {
  height: 4px;
}

nav ul::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 2px;
}

@media (min-width: 768px) {
  nav ul {
    gap: 1rem;
    overflow-x: visible;
    padding-bottom: 0;
  }
}

nav a {
  white-space: nowrap;
}
```

**Estimated Effort**: Small

---

### Task 2.5: Confirmation/Cancel Page Buttons

**File**: `frontend/src/pages/confirm/ConfirmPage.vue`

**Actions**:
1. Stack confirmation buttons on mobile
2. Make buttons full width

**CSS Changes**:
```css
.confirmation-buttons {
  display: flex;
  gap: 1rem;
  justify-content: center;
  margin: 2rem 0;
  flex-wrap: wrap;
}

@media (max-width: 575px) {
  .confirmation-buttons {
    flex-direction: column;
  }

  .confirmation-buttons button {
    width: 100%;
  }
}
```

**Estimated Effort**: Trivial

---

### Task 2.6: Cancel Page Buttons

**File**: `frontend/src/pages/cancel/CancelPage.vue`

**Actions**:
1. Stack action buttons on mobile

**CSS Changes**:
```css
.actions {
  display: flex;
  gap: 1rem;
  margin-top: 1.5rem;
}

@media (max-width: 575px) {
  .actions {
    flex-direction: column;
  }

  .actions > * {
    width: 100%;
    text-align: center;
  }
}
```

**Estimated Effort**: Trivial

---

## Phase 3: Polish & Optimization

### Task 3.1: Lottery Page Responsiveness

**File**: `frontend/src/pages/admin/events/[eventId]/lottery.vue`

**Actions**:
1. Adjust metric grid for mobile
2. Stack panels on mobile
3. Make action buttons responsive

**CSS Changes**:
```css
.summary-metrics {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1fr 1fr;
}

@media (min-width: 768px) {
  .summary-metrics {
    grid-template-columns: repeat(3, minmax(120px, 1fr));
  }
}

.lottery-panels {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1fr;
}

@media (min-width: 1024px) {
  .lottery-panels {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 575px) {
  .panel-actions {
    flex-direction: column;
  }

  .panel-actions button {
    width: 100%;
  }
}
```

**Estimated Effort**: Small

---

### Task 3.2: Registration Page Form

**File**: `frontend/src/pages/registration/RegistrationPage.vue`

**Actions**:
1. Ensure form is mobile-optimized
2. Touch-friendly inputs

**CSS Changes**:
```css
@media (max-width: 767px) {
  form input,
  form select,
  form textarea {
    min-height: 44px;
    font-size: 16px;
  }

  form button[type="submit"] {
    width: 100%;
    min-height: 48px;
  }
}

/* Definition list responsiveness */
dl {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.25rem;
}

@media (min-width: 576px) {
  dl {
    grid-template-columns: auto 1fr;
    gap: 0.5rem 1rem;
  }
}

dt {
  font-weight: bold;
}

@media (max-width: 575px) {
  dd {
    margin-bottom: 0.5rem;
  }
}
```

**Estimated Effort**: Small

---

### Task 3.3: Status Cards Sizing

**Files**: `ConfirmPage.vue`, `CancelPage.vue`, `RegistrationPage.vue`

**Actions**:
1. Adjust padding for mobile
2. Scale icons appropriately

**CSS Pattern**:
```css
.status-card,
.success,
.already-cancelled {
  padding: 1.5rem;
}

@media (min-width: 768px) {
  .status-card,
  .success,
  .already-cancelled {
    padding: 2rem;
  }
}

.status-icon {
  font-size: 2.5rem;
  margin-bottom: 0.75rem;
}

@media (min-width: 768px) {
  .status-icon {
    font-size: 3rem;
    margin-bottom: 1rem;
  }
}
```

**Estimated Effort**: Small

---

### Task 3.4: DebugPage Compact Mobile

**File**: `frontend/src/pages/admin/DebugPage.vue`

**Actions**:
1. Larger touch targets for action links
2. Better contact cell layout

**CSS Changes**:
```css
@media (max-width: 767px) {
  .action-link {
    width: 2rem;
    height: 2rem;
    font-size: 1rem;
  }

  .contact-link {
    width: 2rem;
    height: 2rem;
  }

  .contact-cell {
    justify-content: flex-end;
  }

  .phone-number {
    display: none;
  }
}
```

**Estimated Effort**: Trivial

---

## Testing Checklist

### Device Testing

- [ ] iPhone SE (375px) - Smallest common viewport
- [ ] iPhone 14 (390px) - Standard iPhone
- [ ] iPhone 14 Pro Max (430px) - Large phone
- [ ] iPad Mini (768px) - Small tablet
- [ ] iPad (1024px) - Standard tablet
- [ ] Laptop (1366px) - Common laptop
- [ ] Desktop (1920px) - Full HD

### Page-by-Page Testing

#### EventsPage
- [ ] Filter tabs scroll horizontally on mobile
- [ ] Events table scrolls/transforms correctly
- [ ] Create modal is usable on mobile
- [ ] Edit modal is usable on mobile
- [ ] Registrations modal displays correctly
- [ ] All buttons are touch-friendly

#### DebugPage
- [ ] Registrations transform to cards on mobile
- [ ] Contact icons are tappable
- [ ] Action links are large enough
- [ ] Event headers are readable

#### Lottery Page
- [ ] Metrics grid adapts correctly
- [ ] Panels stack on mobile
- [ ] Buttons are full-width on mobile

#### Registration Page
- [ ] Form inputs don't trigger iOS zoom
- [ ] Submit button is prominent
- [ ] Success message displays correctly

#### Confirm/Cancel Pages
- [ ] Buttons are full-width on mobile
- [ ] Status cards are readable
- [ ] Links are tappable

### Accessibility

- [ ] All touch targets >= 44px
- [ ] No horizontal scroll on page level
- [ ] Text readable at all sizes
- [ ] Focus states visible
- [ ] Color contrast maintained

---

## File Change Summary

| File | Phase | Changes |
|------|-------|---------|
| `src/assets/styles/responsive.css` | 1 | New file - global utilities |
| `src/main.js` | 1 | Import responsive.css |
| `src/pages/admin/EventsPage.vue` | 1, 2 | Form, modal, table, header, tabs |
| `src/pages/admin/DebugPage.vue` | 2, 3 | Table-to-card, touch targets |
| `src/pages/admin/events/[eventId]/lottery.vue` | 3 | Grid, panels, buttons |
| `src/pages/registration/RegistrationPage.vue` | 3 | Form, dl layout |
| `src/pages/confirm/ConfirmPage.vue` | 2, 3 | Buttons, status card |
| `src/pages/cancel/CancelPage.vue` | 2, 3 | Buttons, status card |
| `src/App.vue` | 2 | Hamburger menu |

---

## Rollout Strategy

1. **Implement Phase 1** - Critical fixes ensuring basic mobile usability
2. **Test on real devices** - Validate Phase 1 changes
3. **Implement Phase 2** - Enhanced mobile experience
4. **User feedback** - Gather feedback from stakeholders
5. **Implement Phase 3** - Polish and optimization
6. **Final testing** - Complete device matrix testing
7. **Deploy** - Release to production
