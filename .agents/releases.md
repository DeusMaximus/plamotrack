# Release artifacts (#278)

This is the maintainer procedure. v0.5.1-alpha is the first release to use it, and
nothing here is verified end to end until that release is published. GitHub
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
   **First candidate watchpoints (not yet verified in Actions):** confirm that
   the absolute bundle `COMPOSE_FILE` written to `GITHUB_ENV` overrides the
   job-level source-build value in later steps. The pull/start and running-image
   steps must use the downloaded bundle, not the checkout's build override.
   Also confirm that both native runners find the Compose/buildx plugins through
   the anonymous Docker config's `/usr/libexec/docker/cli-plugins` or
   `/usr/lib/docker/cli-plugins` search paths; the arm64 runner is untested.
   Ordinary source PR CI and local environment substitution do not verify these
   candidate-only runner behaviors.
5. Download the `release-bundle` artifact for the existing deployment/client gate.
   Run `deployment_gate.py` **without** `--source-build` against a directory with
   those release files and its own `.env`. It will not build. A source checkout
   gate uses `--source-build` and is evidence about source, not about release
   digests. Record the observed deployment/client results in the release notes.
6. On the owner's approval, create/push the annotated release tag at exactly the
   candidate commit. Do not move it later. Dispatch **Promote release candidate**
   **on that tag**, supplying the successful run ID. It verifies the workflow,
   run result, repository, source commit, tag and file checksums. It copies the
   tested image indices to version tags and verifies the resulting digests are
   identical; it attaches the same files to a **draft** release.
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

The five release files are `docker-compose.yml`, `.env.example`,
`plamotrack-gunpla.zip`, `release.json` and `SHA256SUMS`. The JSON records version,
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
