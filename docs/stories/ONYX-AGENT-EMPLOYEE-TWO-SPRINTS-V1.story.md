# Onyx — execução agentic e integração natural do humanoide

Status: **InProgress**

## Change Log

| Date | Version | Change | Owner |
| --- | --- | --- | --- |
| 2026-09-05 | 1.1.31 | Owner-authorized documentary normalization; predecessor evidence preserved in C:/MAAX_Assistant/Onyx-Release-Backups/v96-story-before-performance-20260905.md. No new installation claimed. | @po |

## Performance continuation — acceptance criteria

- Preserve humanoid geometry, materials, palette, layout and voice.
- Add an adaptive renderer candidate with a maximum target of 60 FPS; report measured frames separately from targets; respect inactive/reduced-motion states.
- Present latest conversation output without losing the bounded full history.
- Verify changes with deterministic tests and real renderer sampling before release promotion; never label a target as measured FPS.
- Existing capability/integration gates below remain open until their own operational proof exists.

## Performance continuation — tasks

- [x] Preserve the predecessor story and normalize the authorized document structure.
- [x] Implement and test adaptive rendering candidate and measured counters (Node and isolated Chromium; not native release certification).
- [x] Correct latest response/history presentation and test callbacks (actual Qt projection; installed History click remains a separate verification).
- [ ] Qualify and install a successor through release integrity gates.

## Pedido e limites visuais

Preservar o humanoide, sua geometria, shaders, animações, paleta e voz.
Corrigir o retângulo opaco na composição. Verificar capacidades de execução de
tarefas, memória longa e contexto; concluir a remediação em duas sprints.
O inventário de 42 capacidades está em `../onyx/CAPABILITY_AUDIT_2026-09-04.md`.

## Sprint 1 — inicialização, composição e núcleo de trabalho

- [x] Instalar correção do argumento vazio nos atalhos: 1.1.30, instalador exit 0.
- [x] Validar atalhos desktop/Menu Iniciar sem reparo posterior: PASS.
- [x] Validar executável instalado: host e UI construídos; smoke V24 PASS.
- [x] Isolar causa do quadrado: WebGL, canvas de apresentação e captura opacos.
- [x] Implementar sucessores transparentes V4/V5, componente V13 e shell V16.
- [x] Provar em Chromium alpha zero nos cantos do frame e da captura de continuidade.
- [x] Provar que somente fundo/alpha mudaram no renderer; geometria, shaders e animação idênticos.
- [x] Testar MissionStore/MissionWorker: 63 testes PASS, incluindo múltiplas etapas,
  cancelamento, lease, reinício, referências entre etapas e despacho pelo host.
- [x] Testar MemoryStore: 20 testes PASS.
- [ ] Promover shell V16 pela cadeia de aceitação e empacotamento sucessora.
- [ ] Validar composição nativa desktop/mobile, movimento e estabilidade em sessão longa.
- [x] Corrigir lifecycle COM das métricas; 5 testes dedicados com subprocessos reais, sem aviso IUnknown.

## Sprint 2 — operação integrada e qualificação live

- [ ] Executar tarefa fornecida em linguagem natural, obter plano, executar etapas
  permitidas, verificar artefato e recuperar progresso após reinício do aplicativo.
- [x] Validar recuperação de memória relevante em nova sessão e efeito no trabalho (processos independentes, seleção determinística de arquivo).
- [ ] Validar ingestão, origem do conteúdo e recuperação de contexto relevante.
- [x] Validar tarefas longas com espera, erro, retomada, orçamento e cancelamento (núcleo local; sessão live separada).
- [ ] Validar Gemini Live/microfone/saída e câmera/mão nos dispositivos reais.
- [ ] Conectar e testar leitura Microsoft Graph/Google com consentimento do proprietário.
- [ ] Validar adaptadores sociais, legenda, FFmpeg e upload em conta autorizada.
- [ ] Disponibilizar Docker daemon e verificar execução real de plugin no sandbox.
- [ ] Verificar execução de squads, resultados e consumo real por tarefa.
- [ ] Qualificar pacote sucessor, instalar e repetir os testes operacionais.

## Status concreto do agente

Missões e memória não são somente documentos: `main.py` instancia MissionStore e
MissionWorker, inicia/encerra o worker, expõe criação/execução/status/cancelamento,
carrega memória no contexto e oferece `memory_search` e `save_memory`.
Os testes de missões e memória exercitam esses componentes localmente.

Isso não certifica um funcionário universal. Execução depende dos runners e
ferramentas conectados, escopo e orçamento. O worker roda enquanto o aplicativo
está ativo; persistência e recuperação não significam execução com o computador
desligado. Aprendizagem atual extrai preferências revisáveis; não treina pesos do
modelo. Operação com contas externas exige configuração e consentimento reais.

Network Guardian V1 foi acrescentado nesta continuação como subsistema separado
de varredura local por indicadores explícitos, com alertas duráveis e planos de
bloqueio/reversão. Não é serviço contínuo nem detector geral de intrusões; não há
prova de bloqueio automático de ataques. O inventário anterior é histórico.

## Evidência desta continuação

- `python -m unittest discover -s tests -p test_missions.py -q`: 63 PASS.
  O processo encerrou com código 0, mas registrou aviso Win32 IUnknown após OK.
- `python -m unittest discover -s tests -p test_memory_store.py -q`: 20 PASS.
- `python -m unittest discover -s tests -p test_humanoid_transparency_v1.py -q`: 2 PASS.
- Verificador de atalhos instalado: PASS, `repaired_desktop=false`.
- `package_native_startup_smoke_test` no diretório instalado: PASS,
  `real_ui=true`, `host_constructed=true`, `provider_calls=0`.

A instalação 1.1.30 contém a correção de startup, não os novos candidatos visuais.
V4/V5/V13/V16 ainda não substituem os pontos de entrada ativos. As duas sprints
permanecem abertas até promoção e provas operacionais. Os arquivos de aceitação
da versão instalada foram preservados.

## File list

- `qml/web/onyx-frame-pacer-v1.js`
- `qml/web/onyx-humanoid-three-v6.html`
- `qml/web/onyx-humanoid-three-v7.html`
- `tests/test_frame_pacer_v1.cjs`
- `tests/test_conversation_projection_v1.py`
- `tests/test_humanoid_adaptive_v1.py`
- `docs/onyx/PERFORMANCE_CANDIDATE_20260905.md`

- `qml/web/onyx-humanoid-three-v4.html`
- `qml/web/onyx-humanoid-three-v5.html`
- `qml/components/OnyxHumanoidEntityV13.qml`
- `qml/OnyxLiveShellV16.qml`
- `tests/test_humanoid_transparency_v1.py`
- `docs/stories/ONYX-AGENT-EMPLOYEE-TWO-SPRINTS-V1.story.md`
- `core/onyx_hud_orb_v17.py`
- `core/onyx_hud_current_acceptance_v47.py`
- `core/onyx_packaged_runtime_hud_contract_v16.py`
- `core/onyx_packaged_runtime_hud_contract_v16.manifest.json`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V47-E6-001.manifest.json`
- `core/network_guardian_v1.py`
- `core/ffmpeg_runtime_v1.py`
- `tests/test_ffmpeg_runtime_v1.py`
- `tests/test_sysmetrics_com_lifecycle_v1.py`
- `docs/onyx/SYSMETRICS_COM_LIFECYCLE_V1_EVIDENCE.md`
- `core/social_official_adapter_v1.py`
- `core/capability_expansion_service_v1.py`
- `scripts/onyx_social_cli.py`
- `tests/test_social_official_adapter_v1.py`
- `tests/test_social_official_host_v1.py`
- `tests/test_social_bootstrap_v1.py`
- `docs/onyx/SOCIAL_OFFICIAL_ADAPTER_V1.md`
- `core/graph_refresh_vault_v2.py`
- `core/phase8_microsoft_graph_oauth_v2.py`
- `core/dayops_graph_factory_v1.py`
- `core/dayops_connection_v19.py`
- `tests/test_graph_refresh_v2.py`
- `docs/onyx/INTEGRATION_GRAPH_LIVE_20260905.md`
- `docs/onyx/GUARDIAN_FFMPEG_REVIEW_FIXES_V1.md`
- `tests/test_network_guardian_v1.py`
- `tests/test_humanoid_promotion_v47.py`
- `tests/test_mission_memory_subprocess_v1.py`
- `docs/onyx/MISSION_MEMORY_SUBPROCESS_V1_EVIDENCE.md`
- `docs/onyx/NETWORK_GUARDIAN_V1.md`
- `ui.py`
- `main.py`
- `dashboard/server.py`
- `dashboard/static/app.html`
- `scripts/bootstrap_onyx.pyw`
- `scripts/build_release.py`
- `scripts/package_hygiene.py`
- `packaging/onyx.spec`
- `core/version.py`
- `scripts/generate_release_workflow_v96.py`
- `scripts/verify_release_workflow_v96.py`
- `tests/test_release_workflow_transition_v96.py`
- `tests/test_mobile_humanoid_parity_v1.py`
- `tests/test_hud_source_frozen_selection_v1.py`
- `tests/test_capability_expansion_layout_freeze_v1.py`
- `core/onyx_live_activation_google_workspace_v1.py`
- `scripts/launch_onyx_live_google_workspace_v1.pyw`
- `scripts/bootstrap_onyx_live_google_workspace_v1.pyw`

## Continuação — V96 / 1.1.31

O seletor ativo passou a carregar HUD V17 / shell V16, autenticados por
V47 e contrato empacotado V16. A instalação repetida do sucessor agora valida
o host existente antes de reentrar nos predecessores; regressão coberta por teste.
Dashboard mobile também seleciona o renderer transparente V5. Testes Chromium
verificam pixels transparentes na apresentação/captura e progressão de frames
durante fala e atenção nos extremos, em desktop e mobile.

Evidência adicional: 37 testes de bootstrap/HUD/atalhos, 6 do dashboard mobile,
4 testes Chromium e 36 do anel memória/missões/aprendizagem/oportunidades passaram.
O ensaio de startup direto em source encontrou uma pré-condição ausente
(`.venv/Scripts/pythonw.exe`); não foi contado como sucesso de startup. A prova
do pacote sucessor deve passar pelo ambiente produzido pelo empacotador.

Network Guardian V1 acrescenta coleta local e alertas por indicadores explícitos,
com plano de bloqueio e reversão de regras próprias. Não certifica detecção
geral de intrusões nem inclui serviço contínuo de proteção nesta versão.
Novos resultados instalados/live devem constar de evidência posterior ao build;
a story não será fechada por cobertura de contratos ou simples presença de módulos.

### Auditoria de integrações e correções adicionais

- Gemini Live respondeu a uma solicitação mínima real de texto para áudio em
  7,048 s (conexão mais turno completo); não mede latência inicial nem voz física.
- FFmpeg 7.1.1 existe no host, mas o resolvedor recusava o link padrão WinGet.
  A correção aceita somente esse link dentro do pacote Gyan esperado, retorna
  o caminho resolvido e mantém rejeição dos demais escapes. Seis testes PASS.
- Ingestão/refinaria: 64 testes PASS; prova local, não treinamento de pesos.
- Anel agentic (memória, missões, Guild e budgets): 430 PASS, 2 skips.
- Métricas COM: início explícito no host, apartamento por thread e teardown
  balanceado; 87 testes e 47 subtestes PASS, sem aviso IUnknown.
- Compositor transparente: limpar o buffer de verificação antes de cada amostra
  evita aceitar frames vazios/parciais com pixels anteriores; 4 testes Chromium PASS.
- Docker Desktop iniciado por mecanismo existente, mas daemon indisponível e
  início do serviço recusado. Nenhuma configuração de segurança foi contornada.
- Graph corrigido com sucessor OAuth/vault V2 (capacidade nativa 2048 bytes,
  sem truncamento, com readback e validação de conta/escopos). Refresh, identidade,
  mensagens e calendário HTTP 200 em 1,752 s no source; 132 testes PASS.
  Google continua sem configuração/consentimento. Câmera não apareceu no inventário.
- Publicação social não tinha adaptador atribuído ao runtime. Preview local não
  será contado como publicação nem upload. Adaptador oficial Facebook Pages
  para texto implementado e ligado ao CLI existente e configuração explícita
  do host; 80 testes de provider/ledger e 19 de host/bootstrap PASS. Sem chamada
  de publicação real; não suporta upload de vídeo ou outras plataformas.
- Testes de voz, continuidade, encerramento e latência de texto: 90 PASS.
  Não equivalem à qualidade de voz física certificada pelo proprietário.
- Revisão Guardian/FFmpeg: 82 testes PASS; API Windows seleciona netsh sem
  depender de SystemRoot, diretórios vinculados são recusados e probe limitado
  verifica encoders áudio/vídeo (inclusive rejeição de Playwright renomeado).
- O gate final encontrou incompatibilidade do cache decorado FFmpeg com o
  carregador autenticado Google. Substituído por cache limitado com funções
  diretamente verificáveis, preservando timeout, TTL e identidade do binário.
  Os 21 testes FFmpeg passaram; o verificador não foi relaxado.
- Primeiro build V96 recusado no smoke por seletores históricos V12/V15 no
  teste embarcado. Atualizados para V13/V16/WebGL V5, exigindo fundo alpha zero
  e fallback visível somente quando o renderer não está pronto. Dez testes
  reais Qt do grupo de smoke passaram. Nenhum pacote recusado foi instalado.
