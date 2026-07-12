# Documentation Structure

**Last Updated**: 2026-06-23 (reflects polished init + robust shortcut launchers)
**Status**: Clean and organized

---

## Current Structure

### docs/ (Core Documentation)

**User Documentation**:
- **README.md** - Documentation index and navigation
- **TROUBLESHOOTING.md** - Common issues and solutions
- **API_REFERENCE.md** - Complete API documentation

**Developer Documentation**:
- **ARCHITECTURE.md** - System architecture and design patterns
- **DEVELOPMENT.md** - Development setup and workflows
- **DEPLOYMENT.md** - Production deployment guide
- **PERFORMANCE_TUNING.md** - Optimization and benchmarking

---

### docs/features/ (Feature-Specific Documentation)

- **MUSIC_MODE_ARCHITECTURE.md** - Music transcription architecture
  - Separation-first approach
  - Hallucination filtering
  - Multi-language support

---

### docs/archive/ (Historical Documentation)

Contains completed plans, session logs, and superseded documentation.

---

### docs/research/ (Research Notes)

Contains API research, feature research notes, and implementation experiments.

---

## Documentation Guidelines

### What Goes Where

**docs/ (Root)**:
- [done] Current, actively maintained documentation
- [done] User-facing guides
- [done] Developer references
- [done] Architecture and design docs
- [needs-work] Historical or completed plans
- [needs-work] Session-specific logs
- [needs-work] Research notes

**docs/features/**:
- [done] Feature-specific architecture
- [done] Detailed implementation guides
- [done] Complex feature documentation
- [needs-work] General architecture (goes in docs/)

**docs/archive/**:
- [done] Completed plans and initiatives
- [done] Historical documentation
- [done] Session logs and summaries
- [done] Superseded documentation
- [needs-work] Current, active documentation

**docs/research/**:
- [done] API research and exploration
- [done] Feature research notes
- [done] Implementation experiments
- [done] Raw research data
- [needs-work] Finalized documentation

---

## Finding Documentation

### For Users
1. Start with **docs/README.md** - Documentation index
2. Common issues? → **TROUBLESHOOTING.md**
3. API reference? → **API_REFERENCE.md**

### For Developers
1. Getting started? → **DEVELOPMENT.md**
2. Understanding system? → **ARCHITECTURE.md**
3. Deploying? → **DEPLOYMENT.md**
4. Optimizing? → **PERFORMANCE_TUNING.md**

### For Feature Details
1. Music mode? → **docs/features/MUSIC_MODE_ARCHITECTURE.md**

### For History
1. Past decisions? → **docs/archive/**
2. Research notes? → **docs/research/**

---

## [done] Maintenance

### When Adding New Docs

**Ask**:
1. Is this current and actively maintained? → docs/
2. Is this feature-specific? → docs/features/
3. Is this historical? → docs/archive/
4. Is this research? → docs/research/

### When Updating Docs

**Check**:
- Is the information still current?
- Should this be archived?
- Can this be consolidated?
- Is it in the right location?

---

**Everything has its place!**
