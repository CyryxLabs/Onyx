# Onyx — sprint unico de estabilizacao e validacao operacional

Data: 2026-09-05. Solicitacao: consolidar as pendencias existentes em um sprint,
sem remover capacidades para obter um GO artificial. Estado: **EM EXECUCAO / NO-GO**.
Este documento consolida a execucao; nao reescreve as releases nem encerra stories.

## Escopo e fontes

- `../stories/ONYX-SECOND-BRAIN-PHONE-TWO-SPRINTS-V1.story.md` e seu status associado.
- `../stories/ONYX-AGENT-EMPLOYEE-TWO-SPRINTS-V1.story.md`.
- `CAPABILITY_AUDIT_2026-09-04.md`: inventario historico, nao certificacao atual.
- `POST_INSTALL_1_1_31_20260905.md`: evidencia instalada V96 preservada.
- `core/capability_parity_v1.py`: os 42 contratos existentes nao substituem a
  comparacao comportamental com o XLVIII fixado na story Second Brain.

Limites preservados: Cyryx Labs/Onyx, humanoide, layout e voz; consentimento,
orcamento, propriedade das contas, proveniencia e evidencias anteriores.
Nenhuma promessa de protecao contra todos os ataques, lucro garantido, viralizacao
garantida ou treinamento autonomo dos pesos do modelo faz parte da certificacao.

## Fila unica, em ordem de dependencia

| ID | Entrega obrigatoria | Prova para fechar | Estado nesta execucao |
| --- | --- | --- | --- |
| GO-01 | Diagnostico confiavel | Import, navegador, dashboard e isolamento do ambiente | Defeito Windows corrigido; probes locais passaram |
| GO-02 | Voz AB13X e JOUNIVO | Fala/resposta, interrupcao, reconexao e sessao longa em ambos | Bloqueador: voz instalada nao responde; correcao de drain apenas em fonte |
| GO-03 | Contratos de todas as capacidades | Mapear declaracao, dispatcher, caminho positivo, falha e evidencia instalada | Ring parcial aprovado; matriz operacional completa pendente |
| GO-04 | Agente trabalhador | Tarefa natural ate artefato verificado, memoria entre sessoes, retomada e cancelamento | Testes locais passaram; trabalho live integrado pendente |
| GO-05 | Second Brain e aprendizagem | Indexar, citar, excluir privado, atualizar/remover, recuperar no host | Configuracao local criada; 9 notas/2 exclusoes; contexto externo desativado |
| GO-06 | Web, Argos, squads e economia | Pesquisa com fontes, situacao do mundo, especialistas com resultado e custo medidos | Qualificacao operacional integrada pendente |
| GO-07 | E-mail/calendario | Leitura instalada com OAuth; escrita apenas em alvo aprovado | Contratos testados; consentimentos/recibos instalados por conta pendentes |
| GO-08 | Social e documentos | Caption/PDF/video e entrega oficial com recibo/reconciliacao | PDF/local e contratos testados; adaptadores ausentes e entregas live pendentes |
| GO-09 | Plugins | Plugin real no sandbox, limites, falha e cancelamento | Docker daemon indisponivel na verificacao atual |
| GO-10 | Android e iPhone | Chamada aprovada, audio bidirecional, timeout e recuperacao por plataforma | Android UI observada; ambos sem certificacao de chamada Onyx; iPhone indisponivel |
| GO-11 | Camera, mobile e Guardian | Mao real, humanoide estavel, uso mobile, alertas/reversao de regras aprovadas | Validacao fisica/operacional pendente; Guardian nao e IDS geral |
| GO-12 | Release e GO | Suite completa, fontes seladas em sucessora, pacote, instalacao, rollback, repeticao live | V96 instalada; fonte divergente; sem nova instalacao |

GO-08 tambem inclui FAQ/receptionista isolado e callback, Telegram de documentos,
faturamento/propostas/cotacoes com totais deterministas. GO-03 inclui calorias,
repeticoes, lembretes, clipboard, arquivos, navegador/YouTube, personalizacao,
auto-start e demais identificadores do inventario existente. Nenhum item e
considerado concluido apenas porque sua interface ou teste existe.

## Trabalho realizado nesta execucao

1. Reproduzido diagnostico incorreto: subprocesso sem APPDATA buscava dependencias
   em `C:\Users\ppetr\Python`, enquanto o processo principal as carregava de
   `AppData\Roaming\Python`. O filtro de ambiente agora preserva APPDATA e
   LOCALAPPDATA e respeita nomes case-insensitive no Windows. Segredos arbitrarios
   e PYTHONPATH continuam excluidos. Nao foi instalado nenhum pacote novo.
2. Apos a correcao: importacao do runtime, inventario de audio, Chromium e dashboard
   HTTPS/auth/file-roundtrip PASS. `install_ready=true` neste diagnostico significa
   somente pre-requisitos locais; `operationally_verified=false` e `ready=false`.
3. Regressao do diagnostico/audio/config: 72 passed, 48 subtests, 12.12 s.
4. Ring de capacidades: 450 passed, 3 skipped, 280 subtests, 42.05 s. Arquivos:
   test_regressions, test_missions, test_continuous_learning_v1, test_obsidian_v1,
   test_deals_v1, test_phone_brief_v1, test_network_guardian_v1,
   test_social_official_host_v1, test_social_official_adapter_v1,
   test_google_workspace_host_v1, test_graph_refresh_v2. Nao e suite completa.
5. Ruff dos dois arquivos alterados do diagnostico: PASS.
6. Criada configuracao persistente no diretorio privado Second Brain, apontando
   para o Onyx Vault escolhido. Refresh: 9 notas, 2 exclusoes, zero chunks alterados,
   zero rede. `context_enabled=false`: nao e ativacao do contexto no app instalado.
7. Docker info falhou porque o pipe dockerDesktopLinuxEngine nao existe.
8. npm lint/typecheck/test: ENOENT por ausencia de package.json; nao passaram.

## Condicoes externas — nao substituidas por simulacao

- Participacao do proprietario nos testes de fala, mao/camera e iPhone.
- OAuth por conta; conteudo, destinatarios e alvos de teste explicitamente aprovados.
- Consentimento para trechos nao privados do vault entrarem no contexto do provedor.
- Orcamento/limites antes de chamadas, publicacoes e trabalho agentic externo.
- Docker e imagem aprovada para plugins. Nao iniciar containers desconhecidos.
- Certificado Authenticode para distribuicao publica formal; candidato local e
  classificacao diferente e nao satisfaz o GO publico.

Nao houve ligacao, publicacao, envio de mensagem, mudanca de firewall ou instalacao
nesta execucao. Nao ha certificacao 100% nem prazo garantido de fechamento: um unico
sprint e a organizacao solicitada, nao permissao para suprimir os criterios acima.
