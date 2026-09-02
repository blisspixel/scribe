# Release Process

This document defines how Scribe moves from roadmap intent to a versioned GitHub
release. It uses evidence gates instead of delivery dates or effort-duration
estimates.

## Sources of truth

- [ROADMAP.md](../ROADMAP.md) owns unfinished scope, dependency order, target
  versions, and exit criteria.
- [CHANGELOG.md](../CHANGELOG.md) owns user-visible changes. Work stays under
  `Unreleased` until release preparation.
- `pyproject.toml`, `src/scribe/__init__.py`, and `uv.lock` own the package version
  and must agree.
- The versioned README and deployment examples identify the current installable
  GitHub release.
- GitHub required CI on the exact commit is the release gate. A local result from
  another commit is supporting evidence, not a substitute.

## Version selection

Use Semantic Versioning based on the user-facing contract:

- Patch: backward-compatible reliability, security, documentation, and packaging
  corrections.
- Minor: backward-compatible capabilities or materially expanded supported
  behavior.
- Major: incompatible command, configuration, output, installation, dependency,
  or platform-support changes.

The roadmap may name future versions before implementation begins. Those names
are planning targets. Confirm the SemVer impact again when the scope is known. If
the target changes, update the roadmap and explain the change in `Unreleased`
before merging code that depends on the new plan.

Do not bump package metadata for every development commit. Keep changes under
`Unreleased`, then synchronize every version source in the release candidate
commit. This prevents partially updated development versions from appearing
installable.

## Ordered workflow

### 1. Select the target

- Choose the first roadmap version whose prerequisites are complete.
- Confirm its objective, in-scope work, exclusions, and exit criteria.
- Link relevant issues and architecture decisions.
- Split unrelated work into a later version instead of broadening the candidate.

### 2. Implement complete slices

- Update behavior, tests, user-facing recovery, and relevant documentation
  together.
- Add each user-visible change to `CHANGELOG.md` under `Unreleased`.
- Record durable architecture or policy changes in an ADR.
- Keep live credentials, media, transcripts, local paths, and raw evidence out of
  the repository.

### 3. Validate from narrow to broad

- Run focused regression tests while implementing.
- Run formatting, lint, strict types, unit and integration tests, combined branch
  coverage, dependency audit, secret scanning, and package-contract checks.
- Run native source checks when native code changes.
- Run authorized live hardware or provider checks only when the release claim
  requires them.
- Convert every reproducible failure into a regression test or an explicit
  documented limitation.

The command set and current coverage floor are maintained in
[DEVELOPMENT.md](DEVELOPMENT.md).

### 4. Prepare one release candidate commit

- Select the final version from the actual SemVer impact.
- Set that version in `pyproject.toml` and `src/scribe/__init__.py`.
- Refresh `uv.lock` and verify all three values match.
- Move `Unreleased` entries into the versioned changelog section and recreate an
  empty `Unreleased` section.
- Update README and deployment install examples to the candidate version.
- Update roadmap state: mark the release objective complete, identify the next
  target, and keep unfinished scope in its proper later version.
- Build the wheel and source distribution from a clean candidate tree.

Version synchronization should be one reviewable commit. Do not tag it yet.

### 5. Prove the exact commit

- Run the full local release gate.
- Push the candidate to `main` through the repository's protected workflow.
- Wait for every required CI check on the exact commit SHA.
- Confirm `main`, the candidate commit, package metadata, docs, and artifacts all
  identify the same version.
- Stop if any required check is missing, skipped unexpectedly, or failing.

### 6. Publish

- Create the annotated version tag only after required CI passes.
- Push the tag and publish a GitHub release with user-focused notes.
- Attach only artifacts that passed the release contract.
- Include checksums or provider digests and identify any intentionally omitted
  platform artifact.
- Never publish unsigned development prototypes as official native builds.

### 7. Verify the release as a user

- Confirm GitHub reports the new release as latest and its assets are available.
- Match uploaded artifact digests to locally verified artifacts.
- Install the versioned tag or release artifact into a clean tool environment.
- Run `scribe --version`, `scribe doctor`, and the release-specific smoke path.
- Confirm upgrade and rollback instructions still point to valid tags.
- Open a patch item immediately if the published artifact differs from the tested
  candidate or its support claim.

## Required release gate

A Scribe release is ready only when all applicable items pass:

- Version metadata, lockfile, changelog, README, deployment examples, and roadmap
  agree.
- Ruff formatting and lint pass.
- Strict mypy passes for the Python source.
- Required tests pass on every declared Python version and platform.
- Combined statement-and-branch coverage meets the enforced floor.
- Dependency audit and full-history secret scan pass without unreviewed findings.
- Wheel and source-distribution contracts pass, including license evidence and
  exclusion of unintended native payloads or private files.
- Go and Rust checks pass when their sources are present in the release.
- Required live platform or provider evidence is tied to the exact candidate.
- The working tree is clean, `main` is synchronized with its remote, and required
  CI passes on the release SHA.

## Updating the plan during development

Update documentation at the same time as the decision it represents:

| Change | Required update |
|---|---|
| User-visible behavior changes | `CHANGELOG.md` under `Unreleased` and the relevant user guide |
| Support claim changes | README, roadmap, deployment guide, and platform guide |
| Target scope moves | Roadmap version sequence and affected exit criteria |
| Architecture or policy changes | ADR, architecture guide, and roadmap dependency if applicable |
| Version is selected for release | Package metadata, lockfile, changelog section, install examples, and roadmap state |
| Release is published | Verify GitHub latest release, artifacts, installed version, and next roadmap target |

Do not report percentage completion or infer a delivery date from test counts.
Report completed evidence, remaining exit criteria, and blockers instead.

## Hotfix path

A data-loss, security, credential-exposure, or release-artifact defect can preempt
the planned sequence as a patch release. Keep the same quality gate:

1. Record the defect and affected contract.
2. Add a regression test that fails for the defect.
3. Implement the smallest complete fix and recovery guidance.
4. Update `Unreleased` and the roadmap maintenance lane.
5. Run the full applicable gate on the exact patch commit.
6. Publish and verify through the normal tag and release process.

Urgency can narrow scope. It does not permit skipping evidence that protects user
recordings, credentials, or release integrity.
