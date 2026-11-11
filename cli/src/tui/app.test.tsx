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

test("n opens the deploy prompt and submits the source", async () => {
  const sources: string[] = []
  const setup = await testRender(
    <App
      initialContainers={[]}
      load={async () => []}
      onRun={async (source) => {
        sources.push(source)
      }}
    />,
    { width: 100, height: 24 },
  )
  try {
    await setup.renderOnce()
    setup.mockInput.pressKey("n")
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("DEPLOY")
    await setup.mockInput.typeText("nginx:alpine")
    await setup.renderOnce()
    setup.mockInput.pressEnter()
    await Bun.sleep(20)
    await setup.renderOnce()
    expect(sources).toEqual(["nginx:alpine"])
    expect(setup.captureCharFrame()).toContain("queued deploy: nginx:alpine")
  } finally {
    setup.renderer.destroy()
  }
})

test("renders an empty state when no containers exist", async () => {
  const setup = await testRender(<App initialContainers={[]} />, {
    width: 100,
    height: 20,
  })
  try {
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("no containers")
    expect(frame).toContain("no container selected")
  } finally {
    setup.renderer.destroy()
  }
})

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
