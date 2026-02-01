# Documentation Structure

**Last Updated**: January 30, 2026  
**Status**: Clean and organized

---

## 📁 Current Structure

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

## 🎯 Documentation Guidelines

### What Goes Where

**docs/ (Root)**:
- ✅ Current, actively maintained documentation
- ✅ User-facing guides
- ✅ Developer references
- ✅ Architecture and design docs
- ❌ Historical or completed plans
- ❌ Session-specific logs
- ❌ Research notes

**docs/features/**:
- ✅ Feature-specific architecture
- ✅ Detailed implementation guides
- ✅ Complex feature documentation
- ❌ General architecture (goes in docs/)

**docs/archive/**:
- ✅ Completed plans and initiatives
- ✅ Historical documentation
- ✅ Session logs and summaries
- ✅ Superseded documentation
- ❌ Current, active documentation

**docs/research/**:
- ✅ API research and exploration
- ✅ Feature research notes
- ✅ Implementation experiments
- ✅ Raw research data
- ❌ Finalized documentation

---

## 🔍 Finding Documentation

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

## ✅ Maintenance

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

**Everything has its place!** 🚀
