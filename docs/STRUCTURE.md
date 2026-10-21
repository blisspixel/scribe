# Documentation Structure

Status: Canonical documentation map for Scribe 2.13.0.

---

## Current Structure

### docs/ (Core Documentation)

**User Documentation**:
- **README.md** - Documentation index and navigation
- **CLI.md** - User workflows, current flags, exit behavior, and evidence
- **VOICE.md** - Resident voice setup, platform status, and recovery
- **TROUBLESHOOTING.md** - Common issues and solutions
- **API_REFERENCE.md** - Supported programmatic entry points and internal API status
- **RESPONSIBLE_USE.md** - Recording, privacy, cloud-sharing, accuracy, and legal guardrails

**Developer Documentation**:
- **ARCHITECTURE.md** - System architecture and design patterns
- **AGENTIC_BALANCE.md** - Deterministic control flow versus bounded model judgment
- **DEVELOPMENT.md** - Development setup and workflows
- **RELEASE_PROCESS.md** - Version planning, release gates, and publication workflow
- **DEPLOYMENT.md** - Local installation and self-managed operation
- **EVALUATION.md** - Reproducible quality and performance evidence
- **PERFORMANCE_TUNING.md** - Optimization and benchmarking
- **features/SBOM_COMPLIANCE.md** - Local dependency inventory generation

---

### docs/features/ (Feature-Specific Documentation)

- **MUSIC_MODE_ARCHITECTURE.md** - Music transcription architecture
  - Separation-first approach
  - Hallucination filtering
  - Multi-language support
- **VOICE_TRAY_UTILITY_PLAN.md** - Resident tray design, Windows validation status, and follow-ons
- **VOICE_TRAY_MAC_LINUX_VALIDATION.md** - macOS/Linux hardware matrix plan and completion rule
- **POLYGLOT_ARCHITECTURE_PLAN.md** - Go tray and Rust audio native boundaries
- **SBOM_COMPLIANCE.md** - Local dependency inventory generation

---

### docs/adr/ (Architecture Decision Records)

Contains accepted architecture, security, and operational policy decisions.

---

## Documentation Guidelines

### What Goes Where

**docs/ (Root)**:
- Current, actively maintained documentation
- User-facing guides
- Developer references
- Architecture and design docs
- Responsible-use policy
- Not temporary plans, session logs, or raw research

**docs/features/**:
- Feature-specific architecture
- Detailed implementation and validation guides
- Complex feature documentation
- Not general architecture, which belongs in docs/

**docs/adr/**:
- Accepted decisions with durable architectural or policy consequences
- Context, decision, and consequences kept together
- Not temporary analysis or session state

---

## Finding Documentation

### For Users
1. Start with **docs/README.md** - Documentation index
2. Commands and workflows? -> **CLI.md**
3. Resident voice? -> **VOICE.md**
4. Common issues? -> **TROUBLESHOOTING.md**
5. Programmatic use? -> **API_REFERENCE.md**

### For Developers
1. Getting started? → **DEVELOPMENT.md**
2. Understanding system? → **ARCHITECTURE.md**
3. Deploying? → **DEPLOYMENT.md**
4. Optimizing? → **PERFORMANCE_TUNING.md**

### For Feature Details
1. Music mode? → **docs/features/MUSIC_MODE_ARCHITECTURE.md**
2. Resident voice implementation? -> **docs/features/VOICE_TRAY_UTILITY_PLAN.md**
3. Native Go and Rust boundaries? -> **docs/features/POLYGLOT_ARCHITECTURE_PLAN.md**

### For Decisions
1. Accepted architecture and policy decisions? → **docs/adr/**

---

## Maintenance

### When Adding New Docs

**Ask**:
1. Is this current and actively maintained? → docs/
2. Is this feature-specific? → docs/features/
3. Is this a durable architecture or policy decision? → docs/adr/
4. Is this temporary analysis or session state? → ignored .agent/

### When Updating Docs

**Check**:
- Is the information still current?
- Should this be archived?
- Can this be consolidated?
- Is it in the right location?

Keep temporary agent state in the ignored `.agent/` directory, not in tracked
project documentation.
