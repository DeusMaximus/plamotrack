# Release artifacts (#278)

This is the maintainer procedure. Its first run, v0.5.1-alpha (candidate run
35789572692, 2026-09-23), passed the candidate and the deployment gate and was
promoted, then stopped at the draft: GitHub had renamed `.env.example` on upload,
so the draft's own `SHA256SUMS` failed. That tag and its image tags stay, unmoved
and unpublished. v0.5.2-alpha is the first release meant for publication. GitHub
publication and native CI cannot be certified by a local build.

## Candidate, then promotion

1. Complete the version bump and ordinary PR review. The application, pyproject
   and lockfile versions must agree; `vX.Y.Z-alpha[.N]` is the release spelling.
2. With the owner's explicit permission for registry publication, dispatch
   **Release candidate** on the exact release commit, giving that version. It
   pushes only `candidate-RUN-ATTEMPT` tags to
   `ghcr.io/deusmaximus/plamotrack-api` and `plamotrack-web`. These are temporary
   build identifiers, never a supported update channel. The build job's token
   alone can write packages; the native test jobs have no registry credentials.
3. **First use:** the owner must make both GHCR packages public in package
   settings. A newly created package can be private even in a public repository.
   The anonymous native pulls must succeed before claiming a credential-free
   install. If this fails, set visibility and dispatch a new candidate.
4. Wait for the entire candidate run: backend, frontend, and Integration on both
   native amd64 and arm64 runners. The Integration jobs consume the downloaded
   Compose bundle and the recorded digests with `--no-build`, run migrations from
   an empty volume, check running image identities and run the existing
   authenticated ingress/MCP/log checks. PostgreSQL is pinned to one multi-platform
   digest, too. A successful pull alone never passes the gate.
   **Two runner behaviours, observed on the first candidate (run 35789572692):**
   the absolute bundle `COMPOSE_FILE` written to `GITHUB_ENV` did override the
   job-level source-build value — the pull/start step's environment shows the
   bundle's path and the Compose project `release-bundle` — and both native
   runners, arm64 included, ran `docker compose` under the anonymous Docker config
   with only `cliPluginsExtraDirs`. Ordinary source PR CI and local environment
   substitution do not exercise either; if a runner image changes, re-read that
   step's log rather than assuming.
5. Download the `release-bundle` artifact for the existing deployment/client gate.
   Run `deployment_gate.py` **without** `--source-build` against a directory with
   those release files and its own `.env` (the recipe is "Against a release's
   files" in `.agents/deployment-gate/README.md`). It will not build. A source checkout
   gate uses `--source-build` and is evidence about source, not about release
   digests. Record the observed deployment/client results in the release notes.
6. On the owner's approval, create/push the annotated release tag at exactly the
   candidate commit. Do not move it later. Dispatch **Promote release candidate**
   **on that tag**, supplying the successful run ID. It verifies the workflow,
   run result, repository, source commit, tag and file checksums. It copies the
   tested image indices to version tags and verifies the resulting digests are
   identical; it attaches the same files to a **draft** release, then downloads
   the draft's assets and verifies them as a user would. If that read-back fails,
   the draft stays unpublished: inspect it, delete it, fix the bundle, and gate a
   new version — the tag and version image tags already exist and are not moved.
7. Add the reviewed change/data/migration notes and observed deployment/client
   gate results to that draft. Publishing the draft is a separate owner-approved
   action. Alpha releases retain the prerelease flag.

**Dispatch a new candidate instead of rerunning jobs.** Promotion requires attempt
1: partial reruns must not combine an old passing gate with newly built artifacts.
The workflow artifact expires after 30 days; promote while it is retained or gate
a new candidate. Promotion may resume a partial image-tag copy only when every
existing version tag still equals its candidate digest. An existing draft/release
is never overwritten; inspect a partial draft manually before proceeding.

For a manual `release_artifacts.py running` check, use the same working directory,
`COMPOSE_FILE`, project selection and (for source builds) `PLAMOTRACK_SOURCE_TAG`
as the stack's startup command. Identity refusals include the resolved Compose
project and API/migrate/web image references to make a selection mismatch visible.

## Files and version policy

The five release files are `docker-compose.yml`, `env.example`,
`plamotrack-gunpla.zip`, `release.json` and `SHA256SUMS`. Every name must survive
GitHub's upload unchanged — letters, digits, `.`, `-` and `_`, beginning and ending
with a letter or digit — which is why the template is `env.example`, not
`.env.example` (`test_every_release_file_keeps_its_name_as_a_github_asset`). The JSON records version,
source SHA, both platforms, API/web/Postgres index digests and payload checksums.
The API and migrate services name the very same digest. The skill ZIP contains its
parent folder, excludes untracked files, and is reproducible for the same source.
The ZIP filename stays install-friendly; the explicit release URL supplies its
version. The Compose file embeds literal digests, so local image variables cannot
silently substitute a different build. The `.env` file remains operator-owned.

Bundle verification checks each Compose service against the manifest, including
API and migrate separately. It requires the Docker Compose CLI (no running daemon)
to parse the explicit bundle file without interpolation or resolving `.env` files;
image variables are refused even when the caller's environment matches the digest.

Published version tags and assets are immutable by project policy. Fixes, rebuilt
base images and dependency updates get a new version and another candidate gate.
No `latest`, `alpha`, minor-version or other moving channel is published. Never
prune digests referenced by supported release bundles. Candidate-only tags may be
removed after their workflow artifacts expire, retaining every promoted digest.
Existing-install update/backup/restore acceptance remains #285; don't promise a
rollback across migrations on the strength of a fresh installation test.

Registry administrators can technically change a tag; installs pin digests and the
workflow refuses to overwrite a conflicting version. This is not a claim that
GHCR itself enforces immutable tags or that checksums are a signature.
