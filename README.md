# vlabor_agent

Robot agent orchestration for the vlabor stack. Combines an LLM chat
backend, a behavior tree runtime, and a web UI so an operator can
hand a robot a natural-language goal and watch the resulting plan
execute step-by-step.

> Status: **early design / scaffolding**. Nothing works yet. See
> [docs/design/overview.md](docs/design/overview.md) for the architecture
> and roadmap.

## Why a separate project

`vlabor_ros2` runs the robot. `vlabor_agent` decides _what to do
next_ and shows the operator _why_. They have different lifecycles
and different audiences (operator vs developer), so they're not
fused.

The agent is meant to be **machine-agnostic**: today it drives
piper through `vlabor-obs` MCP; tomorrow the same runtime should
drive any robot exposing an MCP surface (so101, aspa-navigation, …).

## Layout

```
vlabor_agent/
├── chat_backend/       Python service: Anthropic API + MCP tool-use loop
├── bt_runtime/         Python service: behavior tree executor (py_trees)
├── web_ui/             Web frontend: chat panel + behavior tree canvas
├── examples/           Example task trees / prompts per robot
├── docker/             Docker compose for the chat-backend + bt-runtime + web-ui
└── docs/design/        Architecture and roadmap
```

## No ROS2 dependency

vlabor_agent **does not depend on ROS2**. It talks to robots only
through MCP servers (today: `vlabor-obs`; tomorrow: whatever else
each robot project chooses to expose). Robot-specific ROS internals
stay in those projects; the agent stays portable.

That keeps the Docker images small (slim Python / Node, no
`ros:humble-desktop` base) and makes the same agent runtime usable
by non-ROS robots later.

## License

Apache-2.0. See [LICENSE](LICENSE).

## Contributing

Internal during the scaffolding phase. Once `chat_backend` and a
minimal `bt_runtime` round-trip a tool call, this will open up
to PRs.
