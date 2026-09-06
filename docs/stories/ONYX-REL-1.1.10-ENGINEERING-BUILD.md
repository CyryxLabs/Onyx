# ONYX-REL-1.1.10 — Engineering build lote mínimo

## Status

**Ready for Review**

## Story

**Como** owner do Onyx,
**quero** consolidar o lote de engineering build 1.1.10 já descrito no handoff,
**para que** auto-start, topic watching, Desktop sweep, YouTube locale e proteção contra symlink possam ser revisados juntos sem ampliar o escopo definido pelo ADR-0062.

## Acceptance Criteria

1. O lote preserva o modelo do ADR-0062: trabalho comum do owner flui, enquanto arquivos de sistema, source tree, symlinks/reparse points e ações `always_explicit` permanecem protegidos.
2. Auto-start oferece habilitar, desabilitar e consultar o início do Onyx no login usando o mecanismo nativo suportado por Windows, macOS ou Linux.
3. Topic watching permite observar e remover tópicos, aplica intervalo e limites, deduplica novidades e não comunica silêncio quando a fonte falha.
4. Desktop sweep usa o Desktop real do owner, incluindo redirecionamento Windows/OneDrive, e não atravessa symlinks ou reparse points durante a varredura.
5. YouTube trending usa a região solicitada ou, quando ausente, o locale do owner em vez de uma região fixa.
6. O conjunto focado reportado no handoff preserva o baseline de **105 testes aprovados** e inclui todos os testes de segurança acrescentados durante a revisão.
7. O build 1.1.10 e a instalação local reportados no handoff concluem como **unsigned engineering build**; isso não prova assinatura, certificação, clean-host, publicação ou release pública.

## Tasks / Subtasks

- [x] Conectar auto-start e seus controles nativos. (AC: 2)
- [x] Conectar topic watching com deduplicação, limites e falha explícita. (AC: 3)
  - [x] Executar polling periódico real no runtime e restaurar watches após restart preservando `interval_ms`.
  - [x] Encaminhar toda busca de topic watching pelo dispatcher, broker e auditoria de `web_search`.
- [x] Corrigir Desktop sweep/known-folder e manter proteção contra links. (AC: 1, 4)
  - [x] Bloquear symlink, junction e reparse point e executar rename por boundary vinculada.
  - [x] Provar no Windows a recusa de junction real e de troca TOCTOU durante `organize_desktop`.
- [x] Derivar YouTube trending do locale do owner. (AC: 5)
- [x] Adicionar e executar testes focados dos invariantes QA desta rodada (34 testes aprovados).
- [x] Integrar o successor HUD acceptance V32 do lote 1.1.10 sem substituir orb V12/QML V11.
- [x] Executar o conjunto focado: **109 passed + 230 subtests**, preservando o baseline de 105 e incluindo os testes acrescentados durante a revisão. (AC: 6)
- [x] Produzir e instalar localmente o engineering build 1.1.10 unsigned; Setup exit 0, hashes instalados iguais ao bundle e preflight instalado exit 0. (AC: 7)

## Dev Notes

- Fonte normativa: `docs/onyx/adrs/ADR-0062-owner-scope-and-v55-transition.md`.
- Fonte de execução: alterações e handoff existentes do lote 1.1.10.
- `accumulated-context.md` não foi localizado neste checkout; nenhuma exigência foi inferida para preencher essa ausência.
- [AUTO-DECISION] O lote autoriza release público? → Não; “build/install local unsigned” limita a evidência ao host local (reason: o handoff não inclui assinatura, certificação ou publicação).
- Não adicionar features nem alterar runtime como parte desta story documental.

## Story Draft Checklist

- [x] Objetivo e valor estão claros e limitados ao handoff.
- [x] Acceptance Criteria são verificáveis e não ampliam o ADR-0062.
- [x] Dependências, proteção contra symlink e limite unsigned estão explícitos.
- [x] Tasks mapeiam para Acceptance Criteria.
- [x] File List contém somente superfícies observadas no lote e esta story.
- [x] Nenhuma alegação de release pública, assinatura ou certificação foi criada.

## CodeRabbit Integration

**Primary Type:** Release engineering
**Secondary Types:** Security, cross-platform runtime
**Quality Gate:** revisar preservação do ADR-0062, proteção contra symlink/reparse e limite local unsigned.

## File List

- `core/version.py`
- `core/autostart_registration_v1.py`
- `core/topic_monitor_v1.py`
- `core/permission_broker.py`
- `core/onyx_hud_current_acceptance_v32.py`
- `core/onyx_packaged_runtime_hud_contract_v1.py`
- `core/onyx_packaged_runtime_hud_contract_v1.manifest.json`
- `actions/computer_settings.py`
- `actions/reminder.py`
- `actions/file_controller.py`
- `actions/desktop.py`
- `actions/youtube_video.py`
- `main.py`
- `packaging/onyx.spec`
- `ui.py`
- `scripts/build_release.py`
- `scripts/package_hygiene.py`
- `scripts/generate_hud_v32_manifests.py`
- `tests/test_autostart_registration_v1.py`
- `tests/test_topic_monitor_v1.py`
- `tests/test_regressions.py`
- `tests/test_onyx_hud_current_acceptance_v32.py`
- `tests/test_native_release_gate_v1.py`
- `tests/test_package_hygiene_v1.py`
- `tests/test_release_preparation_v110.py`
- `tests/test_current_capability_status_v1.py`
- `readme.md`
- `docs/INSTALLATION.md`
- `docs/onyx/CURRENT_CAPABILITY_STATUS_V1.md`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V32-E6-001.manifest.json`
- `docs/stories/ONYX-REL-1.1.10-ENGINEERING-BUILD.md`

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-08-23 | 0.1.0 | Story mínima criada a partir do ADR-0062 e do handoff existente | Chronos (`@sm`) |
| 2026-08-23 | 0.1.1 | QA crítico corrigido; build/install e suíte oficial mantidos pendentes — Status: InProgress | Vulcan (`@dev`) |
| 2026-08-23 | 0.1.2 | Testes Windows adversariais reais adicionados; whitespace da story corrigido | Vulcan (`@dev`) |
| 2026-08-23 | 0.1.3 | HUD acceptance V32 integrado ao lote 1.1.10; orb V12/QML V11 preservados | Vulcan (`@dev`) |

## Dev Agent Record

### Agent Model Used

- Codex (GPT-5)

### Debug Log References

- `python -m pytest --noconftest tests/test_topic_monitor_v1.py tests/test_regressions.py::DesktopSweepBoundaryTests -q` — 34 passed, incluindo junction Windows real e troca TOCTOU nativa.
- `python -m py_compile actions/reminder.py actions/desktop.py core/topic_monitor_v1.py core/permission_broker.py main.py tests/test_topic_monitor_v1.py tests/test_regressions.py` — passed.
- `python -m ruff check actions/reminder.py actions/desktop.py core/topic_monitor_v1.py main.py tests/test_topic_monitor_v1.py` — passed.
- `python -m ruff check --select F tests/test_regressions.py` — passed.
- `python -m pytest --noconftest tests/test_onyx_hud_current_acceptance_v32.py tests/test_packaged_runtime_hud_contract_v1.py tests/test_package_hygiene_v1.py tests/test_native_release_gate_v1.py tests/test_release_preparation_v110.py -q --basetemp <novo>` — 91 passed.
- `python -m ruff check` nas superfícies V32/current/package/native modificadas — passed.
- `python -m py_compile` nas superfícies Python V32/current/package/native modificadas — passed.
- Prova SHA-256 pós-implementação de V30/V31 — todos os oito hashes de acceptance, geradores, testes e manifestos coincidem com o baseline pré-implementação.
- `npm run lint`, `npm run typecheck` e `npm test` — não executáveis neste checkout Python: `Onyx/package.json` não existe.
- `git diff --check` global/scoped incluindo `ui.py` — bloqueado por whitespace/CRLF pré-existente no diff concorrente de `ui.py`; o arquivo não foi reformatado para preservar trabalho alheio.
- `git diff --check -- actions/reminder.py actions/desktop.py main.py core/permission_broker.py tests/test_regressions.py tests/test_topic_monitor_v1.py core/topic_monitor_v1.py` — passed.
- Verificação explícita de trailing whitespace em `docs/stories/ONYX-REL-1.1.10-ENGINEERING-BUILD.md` — passed.
- Coleta pytest normal bloqueada antes dos testes por drift concorrente em `tests/test_onyx_live_activation_v19.py` reportado pelo retirement hook.

### Completion Notes List

- [IDS — ADAPT] `core/topic_monitor_v1.py` permaneceu como abstração de deduplicação/rate-limit; persistência e runtime foram conectados sem duplicar o monitor.
- [IDS — REUSE] `actions.file_controller.SafeOperationGuard` foi reutilizado para vincular raiz Desktop e diretório de destino durante organize/clean.
- [IDS — ADAPT] O fixture de junction Windows existente foi adaptado para `organize_desktop`; neste host a junction foi criada e recusada, sem fallback/skip.
- [IDS — REUSE] `_SAFE_OPERATION_TEST_HOOK` comprovou que a troca adversarial do source falha enquanto o handle nativo está vinculado.
- [IDS — ADAPT] O dispatcher existente em `main.py` agora executa buscas periódicas e manuais de tópicos via `web_search`, preservando broker e audit trail.
- [IDS — ADAPT] V32 segue o contrato V30→V31, autentica o lote 1.1.10 sobre predecessor V31 imutável e mantém `qml/OnyxLiveShellV11.qml` com `core/onyx_hud_orb_v12.py`.
- [IDS — ADAPT] Somente seletores current em `ui.py`, build e package hygiene avançaram para V32; `authenticated_v25_source_receipt` foi preservado por compatibilidade.
- [IDS — ADAPT] O contrato packaged-runtime exclui V32 como autoridade source-only e seu manifesto determinístico foi resealado sem incluir código/testes de desenvolvimento no pacote.
- [AUTO-DECISION] Renomear o receipt V25? → Não; preservar o nome público evita ampliar escopo e mantém compatibilidade.
- O gerador V32 foi executado após estabilização funcional; uma segunda emissão foi necessária após o primeiro teste revelar transcrição incorreta do hash V31. A saída final é determinística e V30/V31 permaneceram byte-for-byte.
- O conjunto focado atual concluiu com **109 passed + 230 subtests**; build e instalação local unsigned concluíram com exit 0, sem alegação de release pública.
