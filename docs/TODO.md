# TODO - Active Task List

## Known Issues & Testing Gaps

### 1. ✅ FIXED: Recording Timestamp Bug

**Issue**: Recording would immediately jump to transcription without actually recording
**Root Cause**: `start_ts` was set before sending start recording command to OBS
**Impact**: If OBS was already recording, it would detect that existing file and skip recording
**Fix**: Set `start_ts` AFTER sending start recording command
**Version**: Fixed in 2.4.1

### 2. ✅ FIXED: OBS CLI Fallback Mode - File Finalization

**Issue**: CLI mode would try to process file while OBS was still recording
**Root Cause**: Main thread didn't wait for user to type 'stop' before finalizing
**Impact**: "moov atom not found" error because file was incomplete
**Fix**: Wait for `stop_event` before attempting to finalize the recording
**Version**: Fixed in 2.4.1

**What Changed**:
- Stop listener thread now starts AFTER file is detected (cleaner UI)
- Main thread waits for user to type 'stop' before processing
- Added 3-second delay after stop command to let OBS finalize
- Then waits for file to stop growing before processing

**Note**: CLI mode still has limitations compared to WebSocket mode:
- Cannot show recording timer
- Cannot verify OBS actually stopped
- Best practice: Use WebSocket mode (Tools > WebSocket Server Settings)

### 3. No Integration Tests for OBS Recording

**Gap**: Tests only mock OBS, don't actually test recording
**Impact**: Recording bugs not caught by test suite (595/595 tests pass but recording has issues)
**Challenge**: OBS integration tests require:
  - OBS installed and running
  - WebSocket configured
  - Actual recording and file detection
  - Hard to automate in CI/CD

**Action Needed**:
- Add manual test checklist for recording
- Document expected behavior vs actual
- Consider adding integration tests that can be run locally (not in CI)

---

## Recent Improvements (Session 3 - 2025-11-19)

### ✅ Grok Logo Issue - Fixed
- **Issue**: XAI images had Grok logo watermark
- **Fix**: Disabled meme bakeoff, use XAI for concepts + OpenAI for images
- **Result**: Clean memes, no logo

### ✅ Meme Creativity - Enhanced
- **Issue**: Too rigid, always forcing templates
- **Fix**: Made AI truly agentic - can create original scenes, not just templates
- **Result**: More creative, meeting-specific memes

### ✅ Recording UI - Improved
- **Issue**: Timer creating new lines, ugly WebSocket errors
- **Fix**: Use raw stdout for timer, suppress ugly stack traces
- **Result**: Clean recording display

### ✅ Recording Bugs - Fixed (2 issues)
- **Issue 1**: Recording jumped straight to transcription
  - **Fix**: Set `start_ts` after sending start command, not before
- **Issue 2**: "moov atom not found" error in CLI mode
  - **Fix**: Wait for user to type 'stop' before processing file
- **Result**: Recording now works correctly in both WebSocket and CLI modes

### ✅ Version Updated
- **Version**: 2.3.1 → 2.4.0 → 2.4.1
- **Changes**: UX improvements, code quality, no emojis, recording fix

---

## High Priority - Verification & Testing

### 1. ✅ VERIFIED: `scribe doctor` Command Works Perfectly

**Status**: ✅ TESTED AND WORKING

**Verification Results:**
- Command is properly wired up in CLI
- Runs all 15 diagnostic checks
- Beautiful output with clear pass/fail indicators
- Shows version 2.4.0 correctly
- All checks passed on test system

**Output Quality:**
- Clean, professional formatting
- Detailed information for each check
- Clear success summary
- No issues found

### 2. Test Outlier Detection in Performance Tracker

**Status**: Just implemented, not tested

**What we added:**
- Outlier detection in `performance_tracker.py`
- Reduces weight to 10% for measurements >3x or <0.33x average

**Action**: Test with intentionally slow run:
1. Run normal transcription
2. Interrupt mid-way (simulate slow run)
3. Run again and verify estimate didn't get skewed

### 3. Verify Adaptive Progress Learning

**Status**: Implemented but not formally tested

**What exists:**
- Performance metrics stored in `~/.scribe/performance/{machine_id}.json`
- Weighted averaging with outlier detection
- Provider-aware estimates

**Action**: Verify learning works:
1. Delete performance file
2. Run transcription (should use defaults)
3. Check performance file was created
4. Run again (should use learned metrics)
5. Verify estimates improved

## Documentation Improvements Needed

### 4. Add Examples to Diagnostics Output

**Current**: Documentation explains what diagnostics does
**Missing**: Example of actual output

**Action**: Run `scribe doctor` and add real output to docs

### 5. Document Performance Metrics File Format

**Current**: Mentioned in code
**Missing**: User-facing documentation

**Action**: Document:
- Where file is stored
- What metrics are tracked
- How to reset if needed
- Privacy implications (machine ID)

## Code Improvements Identified

### 6. ✅ FIXED: Remove Unreachable Code in music_detection.py

**Status**: ✅ COMPLETED

**Issue**: The `is_music()` method had 100+ lines of unreachable code after an early return

**Fix Applied**: Removed all unreachable code, method now cleanly delegates to `analyze_music()`

**Result**: Cleaner code, easier to maintain, no functional change

### 7. Add Confidence Tracking to Performance Tracker

**Current**: Simple weighted average
**Improvement**: Track variance/confidence

**Benefit**: Could show "4-6 minutes" instead of "5 minutes"

**Complexity**: Medium
**Priority**: Low (current system works well)

### 8. Hardware Change Detection

**Current**: Uses same metrics even if GPU changes
**Improvement**: Hash GPU model, reset if changed

**Benefit**: Accurate estimates after hardware upgrade
**Complexity**: Low
**Priority**: Medium

### 9. Per-Duration Learning Buckets

**Current**: Same estimates for all file lengths
**Improvement**: Different estimates for short/medium/long files

**Benefit**: More accurate for edge cases
**Complexity**: Medium
**Priority**: Low

## Testing Needed

### 10. Stress Test with Large Files

**Current**: Tested with normal files (30-60 min)
**Missing**: Test with very large files (2+ hours)

**Action**: Test:
- Memory usage
- Progress accuracy
- Cleanup behavior
- Error handling

### 11. Memory Leak Detection

**Current**: No formal testing
**Missing**: Long-running batch test

**Action**: Run batch transcription of 50+ files and monitor memory

## New Items

### 12. ✅ ENHANCED: Creative Meme Generation (Not Just Templates)

**Status**: ✅ IMPLEMENTED

**Issue**: Meme generation was too rigid - always forcing classic meme templates

**Enhancement**:
- ✅ Made prompt more agentic and creative
- ✅ AI can now choose: Classic template, Original scene, Abstract concept, or Realistic photo
- ✅ Added "visual_approach" field to track creativity type
- ✅ Enhanced image_prompt guidance: "Be specific, vivid, and original"
- ✅ Explicit permission: "You DON'T have to use a classic meme template"
- ✅ Encourages originality: "ORIGINALITY > TEMPLATES when it makes the joke better"

**Result**:
- More dynamic and creative memes
- Can create meeting-specific visuals
- Not limited to "Distracted Boyfriend" and "Drake" templates
- AI has freedom to be truly creative

**Example Approaches Now Possible**:
- Classic: "Distracted Boyfriend meme"
- Original: "Conference room with everyone staring at a single Keystone contract on fire"
- Abstract: "Azure cloud slowly morphing into a VMware logo"
- Realistic: "Exhausted IT manager surrounded by migration documents"

### 13. ✅ FIXED: XAI Image Generation Logo Issue

**Status**: ✅ VERIFIED WORKING

**Issue**: Grok logo watermark appeared in bottom-right corner of XAI-generated images

**Root Cause**: 
- When `SCRIBE_ENABLE_MEME_BAKEOFF=true`, each provider generates images
- If XAI wins bakeoff, its image (with logo) is used
- `SCRIBE_MEME_IMAGE_PROVIDER=openai` only works when bakeoff is disabled

**Solution Implemented:**
- ✅ Disabled meme bakeoff: `SCRIBE_ENABLE_MEME_BAKEOFF=false`
- ✅ XAI generates concepts (great at humor)
- ✅ OpenAI generates images (no logo)
- ✅ Updated `.env` and `.env.example` with explanation

**Testing Results:**
- ✅ Generated test meme
- ✅ User confirmed: **No Grok logo!**
- ✅ Image quality good
- ✅ Solution working as expected

**Aspect Ratio Support:**
- ✅ Supports 3 sizes: 1024x1024 (square), 1536x1024 (landscape), 1024x1536 (portrait)
- ✅ AI chooses optimal size based on meme concept
- ✅ Enhanced prompt to encourage variety (not always square)

**Future Improvement:**
- Could modify bakeoff to decouple concept selection from image generation
- Would allow bakeoff for concepts while always using OpenAI for images

---

## Completed Items (Session 2 & 3)

### ✅ Remove Unreachable Code in music_detection.py
- Removed 100+ lines of dead code
- Cleaner, more maintainable

### ✅ Add Outlier Detection to Performance Tracker
- Prevents skewed estimates from interrupted runs
- 3x threshold with reduced weight

### ✅ Fix JSON Refinement Warning
- Changed WARNING to DEBUG level
- Cleaner user output

### ✅ Clean Up Recording UI
- Removed emoji bullet points
- Professional appearance

### ✅ Remove Emojis from Output
- Text-based indicators (DONE, ERROR, WARNING)
- Consistent, professional output

### ✅ Update Version to 2.4.0
- Reflects significant improvements

---

## Documentation Philosophy Applied

All items follow our documentation philosophy:
- ✅ Honest about what we know vs don't know
- ✅ Clear about what needs verification
- ✅ Specific about actions needed
- ✅ Realistic about priorities
- ✅ Track completed items for reference

---

**Note**: This TODO list is actively maintained during development.
Items are prioritized by impact and complexity.
**Updated**: 2025-11-19 (Session 3)
