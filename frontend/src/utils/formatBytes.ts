export function formatBytes(totalBytes: number): string {
  if (totalBytes < 1024) {
    return `${totalBytes} B`
  }
  if (totalBytes < 1024 * 1024) {
    return `${(totalBytes / 1024).toFixed(1)} KB`
  }
  if (totalBytes < 1024 * 1024 * 1024) {
    return `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`
  }
  return `${(totalBytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}
