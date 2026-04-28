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
├── bt_runtime/         ROS2 Python node: behavior tree executor (py_trees_ros)
├── web_ui/             Web frontend: chat panel + behavior tree canvas
├── examples/           Example task trees / prompts per robot
├── docker/             Docker compose for the chat-backend + web-ui
└── docs/design/        Architecture and roadmap
```

## License

Apache-2.0. See [LICENSE](LICENSE).

## Contributing

Internal during the scaffolding phase. Once `chat_backend` and a
minimal `bt_runtime` round-trip a tool call, this will open up
to PRs.
