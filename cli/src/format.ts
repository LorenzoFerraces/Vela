export function formatTable(headers: string[], rows: string[][]): string {
  const widths = headers.map((header, index) =>
    Math.max(header.length, ...rows.map((row) => (row[index] ?? "").length)),
  )
  const line = (cells: string[]) =>
    cells
      .map((cell, index) => cell.padEnd(widths[index] ?? 0))
      .join("  ")
      .trimEnd()
  return [line(headers), ...rows.map(line)].join("\n")
}

export function formatPorts(ports: { host_port: number; container_port: number }[]): string {
  return ports.map((port) => `${port.host_port}->${port.container_port}`).join(",")
}
