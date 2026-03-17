# Responsive Design Specification

## Funke Event Management System

---

## 1. Executive Summary

This specification defines the responsive design strategy for the Funke Event Management frontend. The goal is to ensure optimal user experience across all device sizes while maintaining the existing Pico CSS foundation.

### Current State
- **Framework**: Pico CSS v2.0.6 (classless, semantic HTML)
- **Layout**: Flexbox (primary) + CSS Grid (secondary)
- **Media Queries**: None (relies on Pico defaults)
- **Issues**: Tables overflow on mobile, forms don't stack, fixed typography

### Target State
- Mobile-first responsive design
- Explicit breakpoint system
- Optimized tables and forms for all screen sizes
- Fluid typography
- Touch-friendly interactions

---

## 2. Breakpoint System

### Defined Breakpoints

| Name | Min-Width | Target Devices |
|------|-----------|----------------|
| `xs` | 0px | Small phones (portrait) |
| `sm` | 576px | Large phones (landscape) |
| `md` | 768px | Tablets |
| `lg` | 1024px | Laptops / Small desktops |
| `xl` | 1280px | Large desktops |

### CSS Custom Properties

```css
:root {
  --breakpoint-sm: 576px;
  --breakpoint-md: 768px;
  --breakpoint-lg: 1024px;
  --breakpoint-xl: 1280px;
}
```

### Media Query Strategy

**Mobile-First Approach**: Base styles target mobile, then enhance for larger screens.

```css
/* Base: Mobile (xs) */
.component { /* mobile styles */ }

/* Tablet and up */
@media (min-width: 768px) {
  .component { /* tablet styles */ }
}

/* Desktop and up */
@media (min-width: 1024px) {
  .component { /* desktop styles */ }
}
```

---

## 3. Layout Patterns

### 3.1 Container Widths

| Breakpoint | Max-Width | Padding |
|------------|-----------|---------|
| xs-sm | 100% | 1rem |
| md | 720px | 1.5rem |
| lg | 960px | 2rem |
| xl | 1140px | 2rem |

### 3.2 Grid System

#### Form Layouts

**Current Issue**: `.form-row` uses fixed `grid-template-columns: 1fr 1fr`

**Solution**:
```css
.form-row {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1fr; /* Mobile: single column */
}

@media (min-width: 768px) {
  .form-row {
    grid-template-columns: 1fr 1fr; /* Tablet+: two columns */
  }
}
```

#### Metric/Stats Grids

**Pattern**: Auto-fit with minimum column width

```css
.stats-grid {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
}
```

### 3.3 Flexbox Patterns

#### Button Groups

```css
.button-group {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

/* Stack vertically on mobile */
@media (max-width: 575px) {
  .button-group--stack-mobile {
    flex-direction: column;
  }

  .button-group--stack-mobile > * {
    width: 100%;
  }
}
```

#### Header Layouts

```css
.page-header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

@media (max-width: 575px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }
}
```

---

## 4. Component Specifications

### 4.1 Navigation Header (App.vue)

| Breakpoint | Behavior |
|------------|----------|
| xs-sm | Hamburger menu, logo only visible |
| md+ | Full horizontal navigation |

**Mobile Menu Requirements**:
- Hamburger icon (☰) toggles slide-out menu
- Menu overlays content (not pushes)
- Close on outside click or X button
- Auth status visible in menu

### 4.2 Tables (EventsPage, DebugPage)

**Problem**: Tables with many columns overflow on mobile.

**Solution A: Horizontal Scroll Container**
```css
.table-container {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

/* Visual indicator for scrollable content */
.table-container::after {
  content: '';
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 20px;
  background: linear-gradient(to right, transparent, white);
  pointer-events: none;
}
```

**Solution B: Card View (Recommended for DebugPage)**
```css
@media (max-width: 767px) {
  .registrations-table {
    display: block;
  }

  .registrations-table thead {
    display: none;
  }

  .registrations-table tr {
    display: block;
    padding: 1rem;
    margin-bottom: 0.5rem;
    border: 1px solid var(--pico-muted-border-color);
    border-radius: var(--pico-border-radius);
  }

  .registrations-table td {
    display: flex;
    justify-content: space-between;
    padding: 0.25rem 0;
    border: none;
  }

  .registrations-table td::before {
    content: attr(data-label);
    font-weight: bold;
    margin-right: 1rem;
  }
}
```

**Column Priority** (show/hide based on screen size):

| Column | xs | sm | md | lg+ |
|--------|----|----|----|----|
| Name | ✓ | ✓ | ✓ | ✓ |
| Email | ✓ | ✓ | ✓ | ✓ |
| Status | ✓ | ✓ | ✓ | ✓ |
| Personen | - | ✓ | ✓ | ✓ |
| Angemeldet | - | - | ✓ | ✓ |
| Telefon | - | - | - | ✓ |
| Notizen | - | - | - | ✓ |

### 4.3 Modals/Dialogs

| Modal Type | xs-sm | md | lg+ |
|------------|-------|----|----|
| Standard | 100% - 1rem | 500px | 600px |
| Wide (forms) | 100% - 1rem | 650px | 750px |
| Extra Wide | 100% - 1rem | 800px | 900px |

**Mobile Modal Behavior**:
```css
@media (max-width: 575px) {
  dialog article {
    margin: 0.5rem;
    max-width: calc(100% - 1rem);
    max-height: calc(100vh - 1rem);
    overflow-y: auto;
  }

  dialog footer {
    flex-direction: column;
    gap: 0.5rem;
  }

  dialog footer button {
    width: 100%;
  }
}
```

### 4.4 Forms

#### Input Sizing

| Breakpoint | Input Height | Font Size |
|------------|--------------|-----------|
| xs-sm | 48px (touch-friendly) | 16px (prevents iOS zoom) |
| md+ | 40px | 14px |

**Touch Target Requirements**:
- Minimum touch target: 44x44px
- Adequate spacing between interactive elements: 8px minimum

#### Form Layout Patterns

```css
/* Single column on mobile */
.form-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Two columns on tablet+ */
@media (min-width: 768px) {
  .form-section--two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }

  /* Full-width fields span both columns */
  .form-section--two-col .full-width {
    grid-column: 1 / -1;
  }
}
```

### 4.5 Cards and Status Badges

#### Status Cards (ConfirmPage, CancelPage)

```css
.status-card {
  padding: 1.5rem;
  text-align: center;
}

@media (min-width: 768px) {
  .status-card {
    padding: 2rem 3rem;
  }
}

.status-icon {
  font-size: 2.5rem;
}

@media (min-width: 768px) {
  .status-icon {
    font-size: 3rem;
  }
}
```

#### Status Badges

```css
.status-badge {
  display: inline-block;
  padding: 0.2rem 0.5rem;
  font-size: 0.7rem;
  white-space: nowrap;
}

@media (min-width: 768px) {
  .status-badge {
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
  }
}
```

### 4.6 Event Info Summary

```css
.event-info-summary {
  display: grid;
  gap: 0.5rem;
}

.event-info-row {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

@media (min-width: 576px) {
  .event-info-row {
    flex-direction: row;
    gap: 0.5rem;
  }

  .event-info-label {
    min-width: 120px;
  }
}
```

---

## 5. Typography

### Fluid Typography Scale

```css
:root {
  /* Base font size */
  --font-size-base: clamp(0.875rem, 0.8rem + 0.4vw, 1rem);

  /* Headings */
  --font-size-h1: clamp(1.5rem, 1.2rem + 1.5vw, 2.5rem);
  --font-size-h2: clamp(1.25rem, 1rem + 1.25vw, 2rem);
  --font-size-h3: clamp(1.1rem, 0.9rem + 1vw, 1.5rem);

  /* Small text */
  --font-size-small: clamp(0.75rem, 0.7rem + 0.25vw, 0.875rem);
  --font-size-tiny: clamp(0.65rem, 0.6rem + 0.25vw, 0.75rem);
}

body {
  font-size: var(--font-size-base);
}

h1 { font-size: var(--font-size-h1); }
h2 { font-size: var(--font-size-h2); }
h3 { font-size: var(--font-size-h3); }

small, .text-small { font-size: var(--font-size-small); }
.text-tiny { font-size: var(--font-size-tiny); }
```

---

## 6. Spacing System

### Responsive Spacing Scale

```css
:root {
  --space-xs: 0.25rem;
  --space-sm: 0.5rem;
  --space-md: 1rem;
  --space-lg: 1.5rem;
  --space-xl: 2rem;
  --space-2xl: 3rem;
}

/* Responsive section spacing */
.section {
  padding: var(--space-md);
}

@media (min-width: 768px) {
  .section {
    padding: var(--space-lg);
  }
}

@media (min-width: 1024px) {
  .section {
    padding: var(--space-xl);
  }
}
```

---

## 7. Touch Interactions

### Touch-Friendly Buttons

```css
/* Minimum touch target size */
button,
a.button,
.action-link {
  min-height: 44px;
  min-width: 44px;
}

/* Larger touch targets on mobile */
@media (max-width: 767px) {
  button:not(.tiny):not(.small) {
    padding: 0.75rem 1.25rem;
  }
}
```

### Swipe Gestures (Future Enhancement)

Consider implementing for:
- Modal dismissal (swipe down to close)
- Table row actions (swipe to reveal delete/edit)
- Navigation (swipe between tabs)

---

## 8. Page-Specific Requirements

### 8.1 Home Page (Home.vue)
- Simple, centered content
- Full responsiveness via Pico defaults
- No changes required

### 8.2 Login Page (LoginPage.vue)
- Centered card layout
- Max-width: 400px on desktop, 100% - 2rem on mobile
- Large touch-friendly button
- No changes required

### 8.3 Registration Page (RegistrationPage.vue)

| Section | Mobile | Tablet+ |
|---------|--------|---------|
| Event Details | Full width, stacked dl | Side-by-side dl |
| Form Fields | Single column | Two columns where logical |
| Submit Button | Full width | Auto width |
| Success Card | Compact padding | Generous padding |

### 8.4 Events Page (EventsPage.vue)

**Critical Changes Required**:

1. **Filter Tabs**: Horizontal scroll on mobile (no wrap)
2. **Events Table**: Card view on mobile
3. **Create/Edit Modals**: Full-screen on mobile
4. **Registrations Modal**:
   - Scroll table horizontally on tablet
   - Card view on mobile
5. **Button Groups**: Stack vertically on mobile

### 8.5 Debug Page (DebugPage.vue)

**Critical Changes Required**:

1. **Event Cards**: Full width, no horizontal constraints
2. **Registrations Table**:
   - Card view transformation on mobile
   - Priority columns only
3. **Action Links**: Larger touch targets
4. **Contact Icons**: Increased size on mobile

### 8.6 Lottery Page (lottery.vue)

1. **Summary Metrics**: 2-column on mobile, 3+ on tablet
2. **Panel Layout**: Full width, stacked on mobile
3. **Participant Lists**: Card view on mobile
4. **Action Buttons**: Full width on mobile

### 8.7 Confirm/Cancel Pages

- Status cards: Reduced padding on mobile
- Buttons: Full width, stacked on mobile
- Icon sizes: Slightly smaller on mobile

---

## 9. Implementation Priority

### Phase 1: Critical (Mobile Usability)
1. [ ] Add responsive form layouts (`.form-row` stacking)
2. [ ] Modal full-screen on mobile
3. [ ] Touch-friendly button sizes
4. [ ] Table horizontal scroll containers

### Phase 2: Enhanced (Better UX)
5. [ ] Table-to-card transformation for DebugPage
6. [ ] Fluid typography implementation
7. [ ] Responsive navigation (hamburger menu)
8. [ ] Column priority/hiding for tables

### Phase 3: Polish
9. [ ] Spacing system standardization
10. [ ] Status badge sizing
11. [ ] Event info summary layout
12. [ ] Swipe gestures (optional)

---

## 10. Testing Requirements

### Device Testing Matrix

| Device Category | Viewport | Test Priority |
|-----------------|----------|---------------|
| iPhone SE | 375x667 | High |
| iPhone 14 | 390x844 | High |
| iPad | 768x1024 | High |
| iPad Pro | 1024x1366 | Medium |
| Desktop HD | 1920x1080 | High |
| Desktop 4K | 2560x1440 | Low |

### Browser Testing

- Safari (iOS) - Primary mobile browser in Germany
- Chrome (Android) - Secondary mobile
- Chrome (Desktop) - Primary desktop
- Firefox (Desktop) - Secondary desktop
- Safari (macOS) - Secondary desktop

### Accessibility Checks

- [ ] Touch targets meet 44x44px minimum
- [ ] Text remains readable at all sizes
- [ ] Form inputs don't trigger iOS zoom (min 16px)
- [ ] Modals are keyboard navigable
- [ ] Focus states visible on all interactive elements

---

## 11. CSS File Structure

### Recommended Organization

```
frontend/src/
├── assets/
│   └── styles/
│       ├── _variables.css      # CSS custom properties
│       ├── _breakpoints.css    # Media query mixins (if using preprocessor)
│       ├── _typography.css     # Font sizing
│       ├── _spacing.css        # Spacing utilities
│       ├── _components.css     # Shared component styles
│       └── main.css            # Imports all partials
```

### Alternative: Scoped Styles Only

Keep all styles in component `<style scoped>` blocks but create a shared CSS file for:
- CSS custom properties (variables)
- Global responsive utilities
- Typography scale

---

## 12. Success Metrics

| Metric | Target |
|--------|--------|
| Mobile Lighthouse Performance | > 90 |
| Mobile Usability Score | 100% |
| Touch Target Compliance | 100% |
| Content Shift (CLS) | < 0.1 |
| Time to Interactive (Mobile) | < 3s |

---

## Appendix A: Current Page Analysis

| Page | Lines | Complexity | Mobile Issues |
|------|-------|------------|---------------|
| EventsPage.vue | 1408 | High | Tables, modals, forms |
| DebugPage.vue | 677 | Medium | Table overflow, small targets |
| lottery.vue | 397 | Medium | Grid layouts, panels |
| ConfirmPage.vue | 359 | Low | Button sizing |
| RegistrationPage.vue | 313 | Low | Form layout |
| CancelPage.vue | 240 | Low | Button sizing |
| LoginPage.vue | 72 | Low | None |
| Home.vue | ~50 | Low | None |
| App.vue | ~100 | Low | Navigation |

---

## Appendix B: Pico CSS Considerations

Pico CSS provides built-in responsiveness, but has limitations:

**Leveraged Features**:
- Semantic form styling
- Typography defaults
- Container max-widths
- Button/input styling

**Override Required**:
- Table responsiveness (Pico tables don't transform)
- Modal sizing (Pico uses fixed widths)
- Grid layouts (Pico is flexbox-based)
- Custom breakpoints (Pico has limited options)

**Compatibility Notes**:
- Avoid `!important` unless overriding Pico defaults
- Use CSS specificity carefully
- Test dark mode compatibility if implementing later
