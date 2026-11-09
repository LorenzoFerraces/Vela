/**
 * Copies text to the system clipboard.
 *
 * `navigator.clipboard` is only exposed in secure contexts, so it is
 * `undefined` when Vela is served over plain HTTP on a non-localhost host
 * (e.g. `http://vela.example:8081`). Reading it throws a TypeError, so both
 * the missing API and a rejected write (denied permission) fall back to the
 * legacy `execCommand` path, which works in insecure contexts.
 *
 * @param text Text to place on the clipboard
 * @returns Resolves once the text is copied, rejects if both strategies fail
 */
export async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    return
  } catch {
    // insecure context, or the write was refused: use the legacy fallback
  }
  if (!legacyCopy(text)) {
    throw new Error('Clipboard copy failed')
  }
}

function legacyCopy(text: string): boolean {
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  const copied = document.execCommand('copy')
  area.remove()
  return copied
}