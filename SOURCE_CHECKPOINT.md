# Onyx V101 — private source-preservation checkpoint

Cyryx Labs. Product source version: 1.2.0. This is a private Git checkpoint,
not an installed update, signed package, public release or operational GO.

## Evidence boundary

- V101 source authority: 695 bound paths, preserved byte-for-byte.
- Source root SHA256:
  `040f3f09334e56c8080650028c19396f4368c439007af55357a3b34ce117a396`.
- V101 fixture SHA256:
  `f0a93e50d4ef85b19a7292786335b99dce22bd8e8f07bc8759d608323d00ef26`.
- Prior local full regression: 51,463 passed, 120 skipped, 706 subtests passed.
  Skips are not operational certification. This full run was performed on the
  original validated snapshot, not rerun on GitHub or on this export.
- Export source verifier and owned Python source lint passed locally.
- Local compiled candidate and two scoped provider-free frozen checks passed.
  These results do not certify physical audio, camera, OAuth or live publishing.

Owned-source lint command:

```text
python -B -m ruff check main.py ui.py setup.py actions core config memory scripts tests browser_tests dashboard
python -B -m scripts.verify_release_workflow_v101
```

The broader stored CI lint commands also traverse vendor sources and historical
verification code and currently fail. They are not represented as passed.
The first source-preservation commit uses `[skip ci]` to avoid automatically
starting paid multi-platform jobs. No release tag or workflow dispatch is made.

## Deliberate exclusions

Owner API configuration, certificates/private keys, live memory databases,
uploads, runtime state, local backups, build/install outputs, test scratch
directories, dependency caches and unreviewed local screenshots are not part
of this checkpoint. Existing historical source evidence/receipts retain their
original bytes; their old statuses and local path references are historical,
not new operational claims. Existing licenses and third-party notices remain.

Git source preservation does not replace the outstanding native owner-data
backup and independent restore check. The existing backup utility cannot yet
handle the measured operational inventory within its validated entry ceilings.
The installed predecessor was not updated by this Git operation.
