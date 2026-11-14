import { expect, test } from "bun:test"
import { testRender } from "@opentui/react/test-utils"

import { App } from "./app"
import type { ContainerInfo } from "../types"

const container: ContainerInfo = {
  id: "aaaaaaaa-1111",
  name: "web",
  image: "nginx:alpine",
  status: "running",
  health: "healthy",
  ports: [],
  labels: {},
  access_url: "http://web.local",
  access_role: "owner",
  source_kind: "image",
  source_label: "nginx:alpine",
  created_at: "2026-11-08T00:00:00Z",
}

test("renders the container list from initial data", async () => {
  const setup = await testRender(
    <App initialContainers={[container]} load={async () => [container]} />,
    { width: 100, height: 24 },
  )
  try {
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("VELA")
    expect(frame).toContain("web")
  } finally {
    setup.renderer.destroy()
  }
})
