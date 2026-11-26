# Third-party notices

Noeon is an independent integration layer. Some upstream source trees are vendored
under `vendor/` for audited integration; their `.git` directories are removed and
their licence files are kept in place. Skills imported by the skill catalog are not
redistributed in this repository: they are fetched at a pinned commit, verified by
SHA-256 and cached locally on installation.

Vendored trees:

- `vendor/deer-flow/` — ByteDance DeerFlow, MIT (`vendor/deer-flow/LICENSE`)
- `vendor/openhands-software-agent-sdk/` — OpenHands Software Agent SDK, MIT
  (`vendor/openhands-software-agent-sdk/LICENSE`)

Referenced third parties:

- Skill catalogs listed in `catalog/sources.toml`, each under its own licence.
  Reference-only sources are not copied. Imported sources are MIT, Apache-2.0 or
  BSD, and per-skill licence declarations take precedence when present.

## DeerFlow

Copyright (c) 2025 ByteDance Ltd. and contributors.

Source: https://github.com/bytedance/deer-flow
License: MIT

## OpenHands Software Agent SDK

Copyright (c) OpenHands contributors.

Source: https://github.com/OpenHands/software-agent-sdk
License: MIT

The complete license texts remain in the upstream repositories. If code is vendored in a future Noeon release, the corresponding license text and notices must be copied into that release.
