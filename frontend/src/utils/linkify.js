// Turn plain admin-entered text into safe HTML with clickable links.
//
// The text (e.g. a festival's participation_hint) is entered by organizers and
// rendered via v-html, so we HTML-escape EVERYTHING first and only then wrap
// bare URLs in anchors — no raw markup from the source can ever reach the DOM.

const ESCAPE_MAP = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function escapeHtml(str) {
  return str.replace(/[&<>"']/g, (c) => ESCAPE_MAP[c])
}

// http(s):// URLs and bare www. URLs.
const URL_RE = /\b(https?:\/\/[^\s<]+|www\.[^\s<]+)/gi

/**
 * Escape `text` and convert URLs into `<a>` links (new tab, noopener).
 * Returns an HTML string safe to use with `v-html`. Empty string for falsy input.
 */
export function linkify(text) {
  if (!text) return ''
  return escapeHtml(text).replace(URL_RE, (match) => {
    // Keep trailing sentence punctuation out of the link target.
    const url = match.replace(/[.,;:!?)]+$/, '')
    const trailing = match.slice(url.length)
    const href = url.startsWith('www.') ? `https://${url}` : url
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${url}</a>${trailing}`
  })
}
