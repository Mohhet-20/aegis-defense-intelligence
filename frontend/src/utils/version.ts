/** "v1" -> "v1", "1.0.0" -> "v1.0.0". Model and dataset versions are free text, and many
 *  already start with "v", so prefixing blindly produced labels like "vv1". */
export function formatVersion(version: string | number | null | undefined): string {
  if (version === null || version === undefined || version === '') return ''
  const v = String(version).trim()
  return /^v/i.test(v) ? v : `v${v}`
}
