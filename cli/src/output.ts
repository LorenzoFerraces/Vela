export function emit<T>(value: T, render: () => string): void {
  if (process.env.VELA_OUTPUT_QUIET === "1") return
  if (process.env.VELA_OUTPUT_JSON === "1") { console.log(JSON.stringify(value, null, 2)); return }
  console.log(render())
}
