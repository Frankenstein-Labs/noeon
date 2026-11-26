# Noeon upstream sources

This directory contains the real source trees used as Noeon integration inputs. They are copied from official repositories at audited commits; their `.git` directories are intentionally removed so Noeon remains a single Git repository.

## DeerFlow

- Upstream: https://github.com/bytedance/deer-flow
- Commit: `f8cde989d9b2cf57eb782c49354e295bedd0d77e`
- Local path: `vendor/deer-flow/`
- Engine path: `vendor/deer-flow/backend/packages/harness/`
- License: MIT, see `vendor/deer-flow/LICENSE`
- Note: the upstream `frontend/` tree is excluded because Noeon is headless; backend, harness, skills, deployment, tests and technical documentation are included.

## OpenHands Software Agent SDK

- Upstream: https://github.com/OpenHands/software-agent-sdk
- Commit: `e0ed3c00121e813c5cf98c792ed764d16d8af3e9`
- Local path: `vendor/openhands-software-agent-sdk/`
- Engine paths: `openhands-sdk/`, `openhands-tools/`, `openhands-workspace/`, `openhands-agent-server/`
- License: MIT, see `vendor/openhands-software-agent-sdk/LICENSE`

Noeon must preserve these notices when upstream code is changed or redistributed. Upstream code is not replaced by mocks or reimplemented by the thin Noeon layer.
