import { expect, test } from "bun:test"

import { resolveContainer } from "./resolve"
import type { ContainerInfo } from "./types"

function container(id: string, name: string): ContainerInfo {
  return {
    id,
    name,
    image: "nginx:alpine",
    status: "running",
    health: "none",
    ports: [],
    labels: {},
    access_url: null,
    access_role: "owner",
    source_kind: "image",
    source_label: "nginx:alpine",
    created_at: "2026-11-08T00:00:00Z",
  }
}

const containers = [
  container("aaaaaaaa-1111", "web"),
  container("bbbbbbbb-2222", "web2"),
  container("cccccccc-3333", "api"),
]

test("exact name wins", () => {
  const result = resolveContainer(containers, "web")
  expect(result.kind).toBe("one")
  if (result.kind === "one") expect(result.container.id).toBe("aaaaaaaa-1111")
})

test("exact id wins", () => {
  const result = resolveContainer(containers, "cccccccc-3333")
  expect(result.kind).toBe("one")
  if (result.kind === "one") expect(result.container.name).toBe("api")
})

test("unique prefix resolves", () => {
  const result = resolveContainer(containers, "ap")
  expect(result.kind).toBe("one")
  if (result.kind === "one") expect(result.container.name).toBe("api")
})

test("ambiguous prefix lists candidates", () => {
  const result = resolveContainer(containers, "web")
  expect(result.kind).toBe("one")
  const ambiguous = resolveContainer(containers, "we")
  expect(ambiguous.kind).toBe("ambiguous")
  if (ambiguous.kind === "ambiguous") expect(ambiguous.candidates).toHaveLength(2)
})

test("unknown name is none", () => {
  expect(resolveContainer(containers, "zzz").kind).toBe("none")
})
