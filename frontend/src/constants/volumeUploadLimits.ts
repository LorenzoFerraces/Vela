/** Per-folder and per-account limits for volume folder uploads (must match backend defaults). */

export const VOLUME_UPLOAD_MAX_BYTES = 100 * 1024 * 1024
export const VOLUME_UPLOAD_USER_QUOTA_BYTES = 150 * 1024 * 1024

export function volumeUploadLimitMegabytes(bytes: number): number {
  return bytes / (1024 * 1024)
}
