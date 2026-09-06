# Phase 4 E1-E5 checkpoint candidate R6

Evidence: `VE-P4-EXIT-CANDIDATE-R6-001`  
Top input: `VE-SCOPE-P4-E1E5-R6-001` plus comprehensive R12  
Artifacts: `VE-ARTIFACTS-P4-E1E5-R6-001`  
Decision: **candidate only; E6 false; activation false; Phase 5 blocked**

R12 freezes 80 current files, including the Windows active-Desktop resolver,
diagnostic launcher path and four shortcut regressions. Windows source and
frozen flows resolve `WScript.Shell.SpecialFolders("Desktop")`; a failure is
logged explicitly before falling back to `Path.home()/Desktop`.

The active shortcut was created at
`C:/Users/ppetr/OneDrive/Desktop/Onyx.lnk` with repository `pythonw.exe`, quoted
`scripts/launch_onyx.pyw`, repository working directory and official icon. The
legacy `C:/Users/ppetr/Desktop/Onyx.lnk` remained byte-identical. No live
process was restarted.

R6 produced fresh source, pytest/JUnit and static evidence. The canonical
external-basetemp run passed 72 tests plus 6 subtests; JUnit records 78 tests,
zero failures/errors/skips. Ruff, `py_compile` and `git diff --check` exited
zero. Eight Phase 4 flags remained default-off, the guarded import probe loaded
no authority module and the disabled-V1 probe wrote no owner state.

The acyclic trust direction is external future E6 registration -> top R6
source-manifest SHA-256 -> R6 artifact manifest -> new R6 bundle/outputs.
Neither manifest hashes itself and the bundle claims no manifest/self hash.
No external anchor exists yet, so E6 remains false and Phase 5 remains blocked.
