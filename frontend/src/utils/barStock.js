/**
 * Helpers for rendering two-unit bar-item stock (spec 011).
 *
 * Stock is stored in serving units. Items with a package_unit also get a
 * "X Kisten + Y Einzel" display breakdown.
 */

export function splitServings(amount, servingsPerPackage) {
  if (!servingsPerPackage) return { packages: null, singles: amount }
  const packages = Math.floor(amount / servingsPerPackage)
  const singles = amount - packages * servingsPerPackage
  return { packages, singles }
}

/**
 * Render a stock amount as a human string.
 * Examples:
 *   formatStock(item, 123)  // "5 Kisten + 3 Flasche · 123 gesamt"
 *   formatStock(item, 123)  // "123 Becher" (no package)
 */
export function formatStock(item, amount = null) {
  const value = amount !== null ? amount : item.current_amount
  if (item.package_unit && item.servings_per_package) {
    const { packages, singles } = splitServings(value, item.servings_per_package)
    const pack = `${packages} ${item.package_unit}`
    const sing = `${singles} ${item.serving_unit}`
    return `${pack} + ${sing} · ${value} gesamt`
  }
  return `${value} ${item.serving_unit}`
}

export function formatExpected(item) {
  if (!item.expected_amount) return null
  if (item.package_unit && item.servings_per_package) {
    const { packages, singles } = splitServings(
      item.expected_amount,
      item.servings_per_package,
    )
    return `Soll: ${packages} ${item.package_unit}${singles ? ` + ${singles}` : ''}`
  }
  return `Soll: ${item.expected_amount}`
}
