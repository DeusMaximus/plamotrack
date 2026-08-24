# Agent skills

plamotrack is deliberately generic — it tracks plastic-model hobbies, not any one of
them. The hobby-specific part is *conventions*: what to call things, how to bucket
grades, when two products are one catalogue entry. Those don't belong in the
application; they belong with your agent.

This folder holds packaged skills for that. Each one is a folder containing a
`SKILL.md` in the open [Agent Skills](https://agentskills.io) format — a Markdown
file with a YAML header that tells the agent when to load it. Install one alongside
the [plamotrack MCP connection](../README.md#an-mcp-server-so-you-can-stop-clicking)
and your agent applies the conventions automatically whenever it touches your
collection.

| Skill | For |
|---|---|
| [`plamotrack-gunpla`](plamotrack-gunpla/) | Gunpla — kit naming, Bandai kit numbers, grade buckets, series, Gundam Markers, decals, categories, retailers |

Like everything else in this repository, the skills are MIT licensed.

## Installing in Claude Desktop

1. Zip the skill folder so `SKILL.md` sits at the top level inside it:

   ```bash
   cd skills && zip -r plamotrack-gunpla.zip plamotrack-gunpla
   ```

   (Or download the folder from GitHub and zip it — the zip must contain the
   `plamotrack-gunpla` folder, not the loose files.)

2. In Claude Desktop, open **Settings → Capabilities**, make sure **Skills** is
   enabled, then choose **Upload skill** and select the zip.

3. Make sure Claude is connected to your plamotrack instance's MCP server — the
   [main README](../README.md#an-mcp-server-so-you-can-stop-clicking) covers that.

That's it. The skill loads itself when a conversation touches your collection —
"log the three kits I just ordered from HLJ" is enough; you don't invoke it by name.

## Other products

Instructions for Claude Code, claude.ai, and other agents are coming soon. In the
meantime: `SKILL.md` is plain Markdown, so most agents can consume its body directly
as instructions if you paste it into whatever standing-context mechanism yours has.

## Contributing a skill

Build armour, aircraft, ships, or model rail instead? A skill for your genre's
conventions is very welcome as a PR — copy the shape of `plamotrack-gunpla`
(concrete naming rules, checked against what plamotrack's fields actually are, with
collector-defined choices labelled as such rather than presented as facts). A fuller
contribution guide is coming with the project's open-source-operations milestone.
