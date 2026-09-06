# Correction — Activation V11 C001 shortcut side effect

Date: 2026-07-23

After C001 E6 acceptance, live shortcut inspection showed the OneDrive Desktop
shortcut already targeted `bootstrap_onyx_live_v11.pyw` while the local Desktop
shortcut still targeted V10. The V11 real-window test constructs a configured
`MainWindow`; V10's configured-owner refresh then invokes the V11 shortcut
seam. That gate therefore could write a shortcut even though the C001
checkpoint and E6 metadata reported zero shortcut writes.

This is an evidence-side-effect correction, not a runtime product defect:
creating or refreshing the canonical shortcut is the production seam's intended
behavior. The accepted C001 files remain immutable. Future physical gates must
intercept `_create_lnk_windows` before constructing a configured window and
report the intercepted call count separately from real promotion.

Operational remediation completed the same day:

- both `C:\Users\ppetr\Desktop\Onyx.lnk` and
  `C:\Users\ppetr\OneDrive\Desktop\Onyx.lnk` were explicitly normalized to the
  accepted V11 bootstrap;
- both were reread after write with the same target, arguments, working
  directory, icon and `Onyx — Cyryx Labs` description;
- the old V10 live processes were stopped before V11 launch.

