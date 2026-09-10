# #241–#244 spike — FastMCP 3.4.5 → 4.0.3 (M6.1 compatibility)

`findings.md` is the spike's report as Codex (GPT-6) wrote it on 2026-09-08 and
Claude re-verified on 2026-09-11 — the record that filed #241 (provider revocation),
#242 (CIMD persistence), #243 (the bump) and #244 (the gate). It was committed on the
local branch `spike/m61-fastmcp4` (head `bbb58e7`; the code commits `0ff1633`…`1c41ae6`)
and moved here by #243 with its absolute file links rewritten to repo-relative ones;
nothing else changed. The line numbers it cites are those of `main` at `925c56d`.

No harness lives here: the seam measurements were disposable pytest files run with
`-p tests.conftest`, and their raw outputs (baseline and full-run logs, the audit
inventory, captured SDK 2 wire traffic, the transport and OAuth seam measurements,
the issuer controls, the packaged matrix and real-client results) were kept outside
the repository under `/private/tmp/plamotrack-m61-fastmcp4-20260908`, which does not
survive a reboot. The probes that mattered became tracked tests in #243:
`backend/tests/test_mcp_eras.py` (the era probes, their four brief-contract
assertions corrected) and the seam control in `backend/tests/test_mcp_oauth.py`.
