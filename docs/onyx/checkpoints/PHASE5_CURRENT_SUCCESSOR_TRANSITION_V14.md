# Phase 5 current-successor transition V14

V14 authenticates the current Onyx 1.1.9 source after correcting a native
Qt/QML close-lifecycle defect. A WinDbg analysis of the installed-process dump
identified reentrant `QQuickWidget` destruction from the window `closeEvent`:
the callback cleared the QML source, reparented and scheduled deletion, then
forced deferred-delete delivery while Qt was still dispatching the widget
event. The source fix quiesces Onyx-owned timers and signals during close and
leaves QObject destruction to the parent hierarchy after the callback returns.

This changes no assistant authority, tool, provider, voice path or HUD feature.

## Boundary

- Immediate predecessor:
  `tests/fixtures/phase5_current_successor_transition_v13.json`
- Immediate predecessor SHA-256:
  `3b7770fb458d2350028ec764418a5ad1071cb34282e0a9e342bfcc76a1d0da42`
- V14 record:
  `tests/fixtures/phase5_current_successor_transition_v14.json`
- V14 record SHA-256:
  `da0f6d07b7dadd22709147cdfb667bbb7d205949d276f82042f1e27a39225190`
- V14 domain-separated aggregate root:
  `a456192a7ef7f05fc1b48ec093d717c2fadfa09e157fe93da8b1abcf2c22df52`

## Current-byte change since V13

| Path | V13 current SHA-256 | V14 current SHA-256 | Reason |
|---|---|---|---|
| `ui.py` | `cbeb75cd18f320ac92a5182a8834aea894ff3ff294d3e8ab75b9178b3a06ee34` | `b3d9c19a3220826403449e914067c0a67fe01077741a53645aa84e6d52ccbc1e` | Quiesces the QML host without reentrant teardown during `closeEvent`. |

All 18 historical identities and seven named-successor identities remain
unchanged. V13 and every earlier transition remain immutable.

## Reproduced validation

- Qt/HUD lifecycle selection: **27 passed**.
- Native Windows/D3D11 close stress: **8/8 clean subprocess exits**, including
  2 ms audio/state signal activity during each iteration.
- Installed crash dump SHA-256:
  `87c8cf11d7c6bfaf72f43572bf22bd83cc7812d6ab3741ba28c5deaed0c7d934`.
- WinDbg classification: `FAST_FAIL_FATAL_APP_EXIT`, with the fatal path
  crossing `QQmlData::destroyed`, `QObject::~QObject`, `QQuickWidget::event`
  and a PySide QML callback.

The V13 installed package and its running soak predate this source correction.
They remain diagnostic evidence only. V14 requires a clean rebuild,
installation and installed-runtime acceptance before it may become the current
Windows candidate.
