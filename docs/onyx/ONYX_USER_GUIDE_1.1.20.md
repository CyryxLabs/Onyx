# Onyx 1.1.20 — Guia completo do usuário

**Produto:** Onyx  
**Empresa:** Cyryx Labs LLC  
**Versão deste guia:** 1.0  
**Versão do aplicativo:** 1.1.20  
**Atualizado em:** 2 de setembro de 2026

## 1. O que é o Onyx

Onyx é um assistente de inteligência artificial pessoal e operacional da Cyryx
Labs. Ele combina conversa por voz e texto, visão da tela e da câmera, controle
do computador, pesquisa, processamento de arquivos, memória local, automações
governadas e integrações opcionais.

O Onyx foi construído para executar ações reais, mas não recebe autoridade
irrestrita. Leituras privadas, alterações locais e efeitos externos podem exigir
uma confirmação na interface confiável do desktop. Credenciais permanecem no
cofre nativo do sistema operacional e nunca devem ser digitadas em uma conversa,
comando ou arquivo de configuração comum.

### Como interpretar o status de uma capacidade

| Estado | Significado |
|---|---|
| **Disponível localmente** | Implementada, acessível no host e verificável sem uma conta externa. |
| **Confirmação necessária** | O Onyx apresenta a ação exata e só continua depois da autorização do proprietário. |
| **Configuração necessária** | Exige dispositivo, aplicativo, navegador, conta, OAuth ou provedor configurado. |
| **Prévia governada** | O Onyx prepara e mostra o resultado, mas não produz o efeito final automaticamente. |
| **Fundação avançada** | O componente existe, porém fica desligado ou fora da experiência comum até a ativação governada. |

Uma capacidade implementada não significa que a conta, dispositivo ou serviço
externo já esteja conectado. E-mail, calendário, publicação social e Gemini Live
dependem das autorizações do proprietário.

## 2. Início rápido

### Abrir o Onyx

No Windows, abra **Onyx** pelo menu Iniciar ou pelo atalho instalado pela Cyryx
Labs. A instalação padrão está em:

```text
%LOCALAPPDATA%\Programs\Cyryx Labs\Onyx\Onyx.exe
```

Ao iniciar, aguarde o estado **READY** ou equivalente. Você pode então:

1. falar normalmente pelo microfone;
2. digitar no campo de comando e pressionar **Enter** ou **Run/Execute**;
3. anexar um arquivo pelo botão **File**;
4. abrir câmera, acesso remoto ou operações pelos controles correspondentes.

### Primeiros pedidos recomendados

```text
Onyx, qual é o status do meu computador?
Pesquise as notícias mais recentes sobre inteligência artificial.
Abra o Chrome.
Lembre-me amanhã às 9h de revisar o calendário.
Analise o arquivo que acabei de anexar.
Mostre quais ações você pode executar.
```

### Como formular um pedido operacional

Para obter um resultado previsível, informe:

- **o objetivo:** o que deve ser feito;
- **o alvo:** arquivo, aplicativo, pessoa, site ou conta;
- **os limites:** o que não pode ser alterado;
- **o resultado esperado:** abrir, resumir, salvar, enviar ou apenas preparar;
- **o momento:** agora, data e hora ou periodicidade.

Exemplo:

```text
Analise este PDF, resuma os riscos em cinco itens e apenas mostre a prévia.
Não salve nem envie nada.
```

## 3. Interface e controles principais

Os nomes podem aparecer em inglês para preservar a identidade visual do produto.

| Controle | Uso |
|---|---|
| **Campo de comando** | Digitar uma pergunta ou instrução. |
| **Run / Execute** | Enviar o texto digitado. |
| **Interrupt** | Interromper imediatamente a fala/resposta atual e voltar a ouvir. A tecla **Esc** oferece o mesmo comportamento. |
| **Mute** | Silenciar ou reativar o áudio conforme o estado exibido. |
| **File** | Selecionar um arquivo para análise ou transformação. |
| **Camera** | Abrir a câmera para uma análise visual autorizada. |
| **Remote** | Exibir o pareamento seguro para celular ou outro dispositivo na rede local. |
| **Operations** | Abrir as projeções operacionais disponíveis. |
| **History** | Consultar o histórico exposto pela sessão/interface. |
| **Access** | Consultar informações de acesso e disponibilidade. |
| **Fullscreen** | Alternar o modo de tela cheia. |
| **Close** | Fechar ou enviar a janela ao comportamento de segundo plano configurado. |
| **Exit Onyx** | Solicitar encerramento completo e governado do aplicativo. |

O humanoide central representa o estado da presença do Onyx. Ele reage a
interação, fala e atenção visual. O visual não concede autoridade adicional e
não substitui os estados textuais de disponibilidade, confirmação ou erro.

## 4. Catálogo das 34 ferramentas conversacionais

Estas são as ferramentas que o modelo pode solicitar ao host. O usuário não
precisa conhecer seus nomes internos: basta pedir a ação em linguagem natural.

### Conversa, informação e visão

| Ferramenta | O que faz | Exemplo de pedido |
|---|---|---|
| `web_search` | Pesquisa geral, notícias, pesquisa aprofundada, preços e comparação. | “Compare estes dois notebooks por preço e bateria.” |
| `weather_report` | Consulta o clima por cidade e período. | “Como estará o tempo em Toronto amanhã à tarde?” |
| `system_status` | Lê CPU, memória, GPU, temperatura, uptime e processos quando disponíveis. | “Meu computador está sobrecarregado?” |
| `screen_process` | Captura, com autorização, a tela ou a câmera para análise. | “Veja minha tela e explique este erro.” |
| `close_camera` | Interrompe a visualização da câmera sem pedir nova confirmação. | “Feche a câmera.” |
| `memory_search` | Procura fatos e contexto previamente aprovados na memória local. | “O que decidimos sobre o projeto Atlas?” |
| `save_memory` | Solicita autorização para guardar um fato útil na memória local. | “Lembre que prefiro relatórios em inglês.” |

### Computador, aplicativos e navegador

| Ferramenta | O que faz | Exemplo de pedido |
|---|---|---|
| `open_app` | Abre um aplicativo, programa ou site. | “Abra o Spotify.” |
| `computer_settings` | Volume, brilho, janelas, Wi-Fi, zoom, abas, tela cheia, bloqueio, atalhos, autostart e energia. | “Defina o volume para 35%.” |
| `computer_control` | Mouse, teclado, clique, digitação, rolagem, arrasto e captura de tela. | “Clique no botão azul à direita.” |
| `browser_control` | Abre sites, pesquisa, navega, preenche campos, troca abas e captura páginas. | “Abra cyryxlabs.com no Edge.” |
| `desktop_control` | Papel de parede, organização, limpeza, listagem e estatísticas do desktop. | “Mostre as estatísticas da área de trabalho.” |
| `shutdown_onyx` | Encerra o Onyx de forma completa. | “Onyx, encerrar.” |

### Arquivos e desenvolvimento

| Ferramenta | O que faz | Exemplo de pedido |
|---|---|---|
| `file_controller` | Lista, cria, lê, grava, procura, copia, move, renomeia e remove arquivos e pastas. | “Encontre os PDFs em Downloads.” |
| `file_processor` | Analisa e transforma imagens, PDF, Word, texto, planilhas, JSON/XML, código, áudio, vídeo, arquivos compactados e apresentações. | “Extraia o texto deste PDF e mostre a prévia.” |
| `undo` | Lista ou reverte a última alteração reversível realizada pelo Onyx na sessão. | “Desfaça a última alteração feita por você.” |
| `code_helper` | Explica código, ajuda a depurar a tela ou executa um arquivo local exato depois de aprovação. | “Explique este arquivo Python.” |
| `dev_agent` | Gera uma prévia imutável de projeto Python. Projetos sem dependências externas podem ser executados/publicados após aprovação exata. | “Prepare um utilitário Python para organizar nomes de arquivos.” |

### Comunicação, mídia e utilidades

| Ferramenta | O que faz | Exemplo de pedido |
|---|---|---|
| `send_message` | Prepara e envia mensagem por um aplicativo autorizado, com confirmação. | “Envie no WhatsApp para Ana: chegarei às 15h.” |
| `reminder` | Agenda lembretes ou acompanha um tópico em segundo plano. | “Avise-me sexta às 14h para enviar o relatório.” |
| `youtube_video` | Pesquisa, reproduz, resume, lê informações ou mostra tendências do YouTube. | “Resuma este vídeo do YouTube.” |
| `flight_finder` | Pesquisa opções de voos e pode preparar um relatório. | “Procure voos de Miami para Toronto em 15 de outubro.” |
| `game_updater` | Lista, instala, atualiza ou agenda atualizações de jogos Steam/Epic quando o cliente está disponível. | “Verifique atualizações dos meus jogos da Steam.” |
| `capability_expansion` | Acessa operações governadas de plugins, clipboard, wellness, personalização e estado social. | “Mostre o status do contador de calorias.” |

### Missões governadas

| Ferramenta | O que faz |
|---|---|
| `mission_create` | Cria o plano de uma missão; criar não significa executar. |
| `mission_status` | Mostra o estado verificado de uma missão. |
| `mission_run` | Solicita aprovação e coloca uma missão autorizada na fila. |
| `mission_cancel` | Cancela uma missão elegível. |
| `mission_pause` | Interrompe uma missão de navegador governado. |
| `mission_takeover` | Entrega ao usuário o controle visível do navegador governado. |
| `mission_resume` | Retoma apenas tipos de missão que suportam retomada. |
| `mission_reconcile` | Registra a decisão do proprietário quando o resultado de uma execução é incerto. |
| `mission_external_agent_cleanup` | Limpa, após confirmação, recursos retidos de uma execução externa isolada. |
| `mission_global_kill` | Aciona o interruptor global de parada das missões de navegador governado. |

## 5. As 42 capacidades do Onyx

O registro de paridade da versão 1.1.20 contém as capacidades abaixo. A coluna
“Dependência” informa o que ainda precisa existir para uso real no computador
ou em uma conta externa.

| # | Capacidade | Uso para o usuário | Dependência principal |
|---:|---|---|---|
| 1 | Sistema de plugins | Instalar, habilitar, inspecionar e executar extensões governadas. | Sandbox Docker certificado; plugin aprovado. |
| 2 | Voz em tempo real | Conversar por áudio com resposta nativa. | Gemini Live, rede, microfone e saída de áudio. |
| 3 | Diálogo afetivo | Ajustar a dinâmica conversacional em modo de áudio suportado. | Preview compatível do Gemini Live. |
| 4 | Áudio proativo | Permitir intervenções de áudio configuradas. | Preview compatível e opção habilitada. |
| 5 | Continuidade de sessão | Rotacionar/reconectar sessões sem perder o contexto permitido. | Gemini Live disponível. |
| 6 | Controle do sistema | Controlar configurações e ações locais do computador. | Suporte do sistema operacional e aprovação. |
| 7 | Tarefas autônomas | Planejar e executar missões locais limitadas. | Missão, orçamento e escopo aprovados. |
| 8 | Consciência visual | Analisar tela/câmera e acompanhar sinais visuais. | Consentimento, câmera/tela e modelo disponível. |
| 9 | Memória persistente | Manter fatos e contexto aprovados entre sessões. | Armazenamento local saudável. |
| 10 | Entrada híbrida | Alternar entre voz e texto. | Interface ativa; microfone apenas para voz. |
| 11 | Briefing matinal | Preparar saudação, notícias e contexto de início. | Opção habilitada e provedor de notícias. |
| 12 | Check-ins proativos | Fazer sugestões após períodos de silêncio. | Opção habilitada. |
| 13 | Memória da sessão | Preservar contexto durante a sessão ativa. | Runtime ativo. |
| 14 | Monitoramento em segundo plano | Acompanhar tópicos e alertar sobre novidades. | Pesquisa web e Onyx em execução. |
| 15 | Monitoramento de hardware | Ler métricas e alertar sobre limites. | Sensores e permissões do host. |
| 16 | Clima | Consultar condições atuais e previsão. | Provedor meteorológico e rede. |
| 17 | Painel de conteúdo | Mostrar resultados e conteúdo dinâmico na interface. | Interface/dashboard disponível. |
| 18 | Pesquisa web multimodo | Search, news, research, price e compare. | Provedor web e aprovação de envio da consulta. |
| 19 | Lembretes inteligentes | Criar alertas no agendador nativo. | Agendador do sistema operacional. |
| 20 | Busca de voos | Encontrar opções no Google Flights. | Navegador, rede e disponibilidade do site. |
| 21 | Atualizador de jogos | Operar atualizações Steam/Epic. | Cliente de jogo instalado e autenticado. |
| 22 | Processamento de arquivos | Ler, analisar e converter formatos suportados. | Dependências do formato; FFmpeg para áudio/vídeo. |
| 23 | Assistência de código | Explicar, revisar e executar arquivo exato aprovado. | Modelo configurado e aprovação para execução. |
| 24 | Controle de navegador | Navegar e interagir com páginas. | Navegador compatível e aprovação. |
| 25 | Mensagens | Enviar mensagens por conta/aplicativo autorizado. | Conta autenticada e confirmação. |
| 26 | YouTube | Reproduzir, resumir, consultar e ver tendências. | YouTube, navegador e transcrição disponível. |
| 27 | Controle do desktop | Organizar desktop e gerenciar papel de parede local. | Integrações do sistema operacional. |
| 28 | Memória de idioma | Lembrar o idioma falado preferido. | Perfil local. |
| 29 | Dashboard remoto | Usar o Onyx pelo celular na rede local. | Pareamento, TLS local, LAN e firewall. |
| 30 | Inicialização automática | Abrir o Onyx no login do usuário. | Registro de inicialização do sistema. |
| 31 | Inteligência de clipboard | Capturar uma cópia explícita e temporária do texto autorizado. | Opt-in e gesto explícito; conteúdo não é exposto por voz. |
| 32 | Personalização do assistente | Idioma, alias conversacional e preferências. | Confirmação do proprietário. |
| 33 | Contador de repetições | Contar movimentos a partir de sinais da câmera. | Calibração física da câmera. |
| 34 | Upload de vídeo | Preparar legenda, vincular vídeo e publicar por adaptador oficial. | OAuth, conta de teste, consentimento exato e recibo do provedor. |
| 35 | Contador de calorias | Registrar, corrigir, confirmar e totalizar calorias/exercícios. | Banco local; confirmação para rascunhos visuais. |
| 36 | Seleção de voz | Escolher entre vozes Gemini suportadas. | Gemini Live. |
| 37 | Seleção de áudio | Escolher microfone e dispositivo de saída. | Dispositivo físico presente. |
| 38 | Controle de memória pelo proprietário | Consultar, exportar, limitar ou apagar memória. | Acesso local do proprietário. |
| 39 | Desfazer limitado | Reverter a alteração local reversível mais recente. | Registro de desfazer válido na sessão. |
| 40 | Confirmação do proprietário | Bloquear ações sensíveis até confirmação confiável. | Interface local confiável. |
| 41 | Resolução de ações locais | Converter pedidos claros em ações locais declaradas. | Ação reconhecida; pedidos desconhecidos são recusados. |
| 42 | Diagnósticos Unicode seguros | Exibir diagnósticos internacionais sem quebrar o console do Windows. | Runtime Windows. |

## 6. Voz, idioma e dispositivos de áudio

### Conversar por voz

Fale normalmente quando o Onyx estiver em estado de escuta. O idioma pode ser
detectado e lembrado localmente. Para interromper uma resposta, pressione
**Esc** ou use **Interrupt**.

O desempenho depende de:

- qualidade e exclusividade do microfone;
- dispositivo de saída correto;
- conexão com o Gemini Live;
- disponibilidade e latência do provedor;
- ruído ambiente e eco do próprio alto-falante.

### Selecionar a voz

As vozes aceitas pelo controle avançado são `Charon`, `Puck`, `Kore`, `Fenrir`
e `Aoede`. Em uma instalação por código-fonte:

```powershell
python scripts/onyx_audio_cli.py status
python scripts/onyx_audio_cli.py voice Charon
```

### Selecionar entrada ou saída

```powershell
python scripts/onyx_audio_cli.py device input "Nome exato do microfone"
python scripts/onyx_audio_cli.py device output "Nome exato do alto-falante"
```

Reinicie o Onyx depois de alterar a rota caso o dispositivo já estivesse aberto
por outra aplicação.

## 7. Tela, câmera e contador de repetições

Pedidos típicos:

```text
Veja minha tela e diga por que este formulário falhou.
Abra a câmera e acompanhe minha mão.
Conte minhas repetições deste exercício.
Feche a câmera.
```

A captura acontece somente quando a ferramenta visual é chamada. A câmera deve
ter permissão no sistema operacional. O contador de repetições requer calibração
física para a posição, iluminação e distância do usuário; uma simulação ou teste
de código não substitui essa calibração.

Para pré-visualizar uma sequência de sinais sem executar uma sessão completa:

```powershell
python scripts/onyx_vision_repetition_cli.py `
  --activity pushup `
  --sample samples.json `
  preview-sequence
```

## 8. Arquivos, documentos, mídia e desfazer

### Formatos e operações

- **Imagens:** descrever, OCR, redimensionar, comprimir, converter e informar.
- **PDF:** resumir, extrair texto, converter para Word e informar.
- **Word/texto:** resumir, corrigir, reformatar, orientar tradução e contar palavras.
- **CSV/Excel:** analisar, calcular estatísticas, filtrar, ordenar e converter.
- **JSON/XML:** validar, formatar e analisar.
- **Código:** explicar, revisar, documentar, testar ou executar dentro das regras.
- **Áudio/vídeo:** informar, cortar, converter, extrair áudio/frame, comprimir e transcrever.
- **Arquivos compactados:** listar ou extrair.
- **Apresentações:** resumir, extrair texto e analisar.

Para usar, clique em **File**, selecione o arquivo e descreva a operação. Leituras
privadas exigem aprovação. Resultados gerados por IA, OCR ou transcrição são
mostrados primeiro como prévia; não são salvos automaticamente porque os bytes
finais ainda não existiam no momento da autorização inicial. Conversões
determinísticas podem ser salvas quando a operação exata estiver autorizada.

### Desfazer

“Desfaça a última alteração feita por você” usa o journal limitado do Onyx. Isso
é diferente de “pressione Ctrl+Z”, que atua apenas no aplicativo em primeiro
plano. Exclusões, efeitos externos e operações sem inversão segura podem não ser
reversíveis.

## 9. Pesquisa, notícias, clima, voos e YouTube

Exemplos:

```text
Pesquise as notícias de hoje sobre segurança de IA.
Faça uma pesquisa aprofundada sobre agentes multimodais e cite as fontes.
Compare os preços do produto A e do produto B.
Mostre o clima de Orlando no próximo sábado.
Procure voos de MIA para YYZ para duas pessoas em classe econômica.
Mostre os vídeos em alta no YouTube nos Estados Unidos.
```

Consultas web enviam o texto necessário a serviços externos e, por isso, podem
exigir aprovação. Resultados dependem da disponibilidade e das condições dos
sites. Resumos de YouTube dependem de uma transcrição acessível e não representam
acesso oficial irrestrito a legendas de qualquer vídeo.

## 10. Lembretes, tópicos e comportamento proativo

### Lembrete com data e hora

```text
Lembre-me em 5 de setembro de 2026 às 14h de revisar o orçamento.
```

O Onyx usa o agendador nativo do sistema. Horários passados são recusados.

### Acompanhar um tópico

```text
Acompanhe notícias sobre a empresa Example Corp.
Liste os tópicos que você está acompanhando.
Verifique agora o tópico Example Corp.
Pare de acompanhar Example Corp.
```

O monitor informa somente itens considerados novos dentro do estado mantido. Ele
depende de pesquisa web e normalmente precisa que o Onyx permaneça disponível.

### Briefing e check-ins

O briefing de inicialização e as sugestões proativas são desligados por padrão.
Devem ser habilitados conscientemente na configuração não secreta do proprietário.
Ativá-los pode gerar chamadas ao provedor e uso de rede.

## 11. Memória, privacidade e personalização

O Onyx mantém memória semântica e episódica em SQLite local. Ele não deve guardar
senhas, chaves, tokens, cookies, credenciais ou transcrições brutas.

Pedidos úteis:

```text
Lembre que meu idioma preferido para relatórios é inglês.
O que você lembra sobre o projeto Atlas?
```

O salvamento de um fato sugerido pelo modelo requer confirmação. Em uma instalação
por código-fonte, controles avançados incluem:

```powershell
python -m memory.memory_manager list
python -m memory.memory_manager search "projeto Atlas"
python -m memory.memory_manager forget editor --category preferences
python -m memory.memory_manager export memory/exports/onyx-memory.json
python -m memory.memory_manager privacy off
python -m memory.memory_manager retention --max-episodes 2000 --min-salience 0.15
```

Idioma e alias conversacional:

```powershell
python scripts/onyx_identity_cli.py status
python scripts/onyx_identity_cli.py language-set pt-BR
python scripts/onyx_identity_cli.py alias-set "Onyx"
python scripts/onyx_identity_cli.py language-clear
python scripts/onyx_identity_cli.py alias-clear
```

Um alias muda apenas a forma de tratamento. O produto e a identidade legal
permanecem **Onyx by Cyryx Labs**.

## 12. Calorias, exercícios e wellness

O wellness tracker registra dados locais com identidade do proprietário,
workspace, horário, fuso e chave de idempotência. Ele suporta:

- registrar calorias;
- registrar exercício e unidade;
- criar rascunho derivado de visão;
- listar entradas;
- corrigir, confirmar ou remover uma entrada;
- calcular totais por dia e fuso.

Exemplos conversacionais:

```text
Registre 620 calorias no meu almoço de hoje.
Registre 30 minutos de caminhada.
Mostre meu total de calorias de hoje.
Corrija a entrada anterior para 580 calorias.
```

Uma estimativa obtida por câmera é sempre um rascunho e precisa de confirmação;
ela não é medição médica ou nutricional. Para administração por código-fonte:

```powershell
python scripts/onyx_personal_tools_cli.py wellness --help
```

## 13. Social media, legendas e vídeo

O fluxo social separa criação, prévia, consentimento, despacho e reconciliação.
O Onyx não deve publicar somente porque produziu uma legenda.

### Gerar uma legenda

```powershell
python scripts/onyx_social_cli.py generate `
  --brief "Explique como agentes reduzem trabalho repetitivo" `
  --brand "Cyryx Labs" `
  --platform linkedin `
  --audience "executivos de tecnologia" `
  --objective education `
  --provider local
```

Para usar Gemini na criação, selecione `--provider gemini` e autorize
explicitamente a rede com `--allow-provider-network`. A geração não publica.

### Vincular um vídeo

O comando `video-preview` valida que o arquivo está dentro de uma raiz controlada,
liga a identidade do vídeo à prévia e mantém uma concessão com tempo limitado.
FFmpeg é necessário para várias operações de vídeo.

```powershell
python scripts/onyx_social_cli.py video-preview `
  --workspace-id cyryx-main `
  --principal-id owner `
  --account-id social-test `
  --target instagram `
  --caption "Legenda aprovada" `
  --controlled-root "C:\Social\Ready" `
  --media-file "C:\Social\Ready\video.mp4"
```

### Publicar

A publicação real exige:

1. adaptador oficial da plataforma;
2. OAuth e conta vinculada pelo proprietário;
3. alvo exato, legenda e mídia exibidos em prévia;
4. consentimento exato;
5. somente um despacho permitido;
6. recibo do provedor e, quando necessário, leitura/reconciliação.

Sem esses elementos, o Onyx permanece em prévia governada. Interfaces web ou
aplicativos controlados visualmente não devem ser confundidos com um adaptador
oficial e seu recibo.

## 14. E-mail e calendário

### Microsoft 365 / Outlook / Microsoft Graph

O executável auxiliar instalado é `Onyx-DayOps.exe`. Ele prepara uma conexão
read-only para um briefing de calendário e metadados de mensagens não lidas.
Antes do primeiro uso, a organização/proprietário precisa criar ou selecionar o
aplicativo público **Onyx by Cyryx Labs** no Microsoft Entra e conceder os escopos
delegados necessários.

Configuração básica, usando apenas identificadores públicos:

```powershell
$env:ONYX_PHASE8_MS_GRAPH_CLIENT_ID="<client-id-publico>"
$env:ONYX_PHASE8_MS_GRAPH_TENANT_ID="<tenant-id-publico>"
$env:ONYX_PHASE8_MS_GRAPH_ACCOUNT_ID="<conta-esperada>"
$env:ONYX_DAYOPS_WORKSPACE_ID="cyryx-main"
$env:ONYX_DAYOPS_PRINCIPAL_ID="owner"
$env:ONYX_DAYOPS_CREDENTIAL_ALIAS="microsoft-primary"

& "$env:LOCALAPPDATA\Programs\Cyryx Labs\Onyx\Onyx-DayOps.exe" prepare
& "$env:LOCALAPPDATA\Programs\Cyryx Labs\Onyx\Onyx-DayOps.exe" status
& "$env:LOCALAPPDATA\Programs\Cyryx Labs\Onyx\Onyx-DayOps.exe" sign-in
```

O login mostra a URL e o código de dispositivo da Microsoft. O refresh token é
guardado no cofre nativo. Para desconectar:

```powershell
& "$env:LOCALAPPDATA\Programs\Cyryx Labs\Onyx\Onyx-DayOps.exe" disconnect
```

O DayOps comum é read-only. Contratos de criação de evento, envio de e-mail e
tarefas existem separadamente, mas não devem ser apresentados como ativos sem
escopos de escrita, nonce durável, confirmação e teste live específicos.

### Google Workspace / Gmail / Google Calendar

O conector Google Workspace existe no código-fonte e permanece dependente do
OAuth do proprietário. O fluxo administrativo por código-fonte é:

```powershell
python scripts/onyx_google_workspace.py status --json
python scripts/onyx_google_workspace.py configure `
  --owner-id owner `
  --workspace-id cyryx-main `
  --account-id user@example.com `
  --client-id "<client-id-publico>" `
  --callback-port 8765
python scripts/onyx_google_workspace.py connect `
  --enabled `
  --owner-id owner `
  --workspace-id cyryx-main `
  --account-id user@example.com `
  --client-id "<client-id-publico>" `
  --callback-port 8765
```

Depois do consentimento, os testes explícitos são `test-gmail` e
`test-calendar`. Não coloque client secret, access token ou refresh token em
argumentos. O CLI Google não é um executável de usuário separado na instalação
1.1.20; é uma superfície administrativa do checkout autorizado.

## 15. Plugins

Plugins são extensões declaradas por manifesto e executadas em um sandbox
governado. Eles não herdam automaticamente rede, escrita ou acesso aos dados do
usuário.

Fluxo recomendado:

1. inspecionar o manifesto e a origem;
2. instalar com o digest de aprovação exato;
3. habilitar o plugin;
4. executar somente uma capability declarada;
5. desabilitar ou remover quando não for mais necessário.

Exemplo administrativo:

```powershell
python scripts/onyx_plugin_cli.py `
  --registry runtime/plugins/registry.sqlite3 `
  --workspace cyryx-main `
  status

python scripts/onyx_plugin_cli.py `
  --registry runtime/plugins/registry.sqlite3 `
  --workspace cyryx-main `
  install path/to/manifest.json --approve <digest-exato>

python scripts/onyx_plugin_cli.py `
  --registry runtime/plugins/registry.sqlite3 `
  --workspace cyryx-main `
  execute <plugin-id> <capability> --payload '{}'
```

O Docker Desktop precisa estar disponível para o sandbox nativo certificado.
Um plugin instalado continua sem autoridade até ser habilitado e autorizado.

## 16. Missões e autonomia governada

Uma missão é uma sequência limitada de passos com estado durável, orçamento,
deadline, idempotência e evidência. Estados possíveis incluem `draft`,
`awaiting_approval`, `running`, `waiting`, `paused`, `succeeded`, `failed` e
`cancelled`.

### Fluxo seguro

1. peça ao Onyx para **criar** a missão;
2. revise escopo, raiz, passos, limites, orçamento e digest;
3. aprove a missão exata;
4. peça para executar;
5. acompanhe o status;
6. pause, assuma o controle, cancele ou acione o kill switch se necessário;
7. se o resultado ficar incerto, reconcilie antes de qualquer nova tentativa.

Exemplo:

```text
Crie uma missão somente de leitura para auditar os arquivos de documentação
deste workspace. Não execute ainda.
```

Ativar o perfil de autonomia não elimina confirmações para mensagens, exclusão,
pagamento, publicação, instalação, execução de código, energia, segurança ou
rede. Raízes e arquivos protegidos continuam bloqueados.

## 17. Controle remoto e celular

O dashboard móvel usa a mesma identidade Onyx e o humanoide distribuído pelo
runtime desktop. Para conectar:

1. mantenha computador e celular na mesma rede local;
2. abra o Onyx no computador;
3. pressione **Remote**;
4. escaneie o QR code exibido;
5. abra a página de pareamento e confirme o código visível;
6. se o navegador solicitar, revise e aceite o certificado TLS local
   autoassinado para aquela instalação;
7. mantenha o Onyx desktop aberto durante a sessão.

Se o QR code apontar para um endereço inacessível, desative temporariamente VPNs
que isolam a LAN ou use o endereço local indicado. O Onyx não altera firewall ou
perfil de rede automaticamente. Aprovações críticas continuam pertencendo ao
canal confiável do desktop; estar autenticado no celular não equivale à presença
física diante do computador.

## 18. Argos e “situação do mundo”

Argos é a fundação original da Cyryx Labs para inteligência sobre eventos do
mundo. Ele organiza fontes registradas, direitos de uso, categorias, severidade,
confiança, ranking e citações. Argos informa; ele não transforma um sinal em ação
automática.

Na versão atual, o núcleo Argos é uma fundação avançada e desligada por padrão.
Fontes live precisam ser aprovadas e conectadas pela cadeia de ingestão antes que
um usuário possa tratar “situação do mundo” como monitoramento operacional em
tempo real. Quando não houver fonte live conectada, o Onyx deve informar a
indisponibilidade em vez de inventar dados.

## 19. Inicialização automática, segundo plano e encerramento

Pedidos disponíveis:

```text
Inicie o Onyx automaticamente quando eu entrar no Windows.
Desative a inicialização automática.
Qual é o estado da inicialização automática?
Feche a câmera.
Interrompa a missão atual.
Encerre o Onyx completamente.
```

O encerramento completo executa limpeza cooperativa de áudio, câmera, workers,
dashboard, missões e recursos pertencentes ao processo. Evite finalizar o
processo à força, exceto quando a própria recuperação governada indicar que o
encerramento normal falhou.

## 20. Aprovações e segurança

### Quando o Onyx pede confirmação

Confirmação é esperada para ações como:

- ler dados privados, tela, câmera, clipboard ou memória;
- alterar arquivos, configurações, janelas ou entrada de teclado/mouse;
- abrir aplicativos em contextos sensíveis;
- enviar mensagens, publicar conteúdo ou criar efeitos em contas externas;
- executar código;
- instalar plugin;
- encerrar aplicativos, o computador ou o próprio Onyx;
- iniciar uma missão com efeitos ou custos.

Leia sempre o alvo, os argumentos e o efeito apresentado. Recuse quando o
pedido não corresponder ao que você solicitou. Um texto como `confirmed=true`
enviado pelo modelo não é aprovação.

### Proteções importantes

- ações desconhecidas falham fechadas;
- diretórios de sistema, credenciais e arquivos protegidos têm regras próprias;
- links simbólicos/reparse points não podem redirecionar silenciosamente uma operação;
- exclusão usa mecanismos recuperáveis/seguros quando disponíveis;
- logs de auditoria registram estrutura e resultado, não conteúdo privado bruto;
- uma ação de resultado incerto não é repetida automaticamente;
- publicação usa prévia, consentimento exato, despacho único e reconciliação;
- plugins e executores não recebem rede ou escrita por padrão.

## 21. Diagnóstico e solução de problemas

### O Onyx não abre

1. confirme que está usando `Onyx.exe` da pasta **Cyryx Labs**;
2. encerre apenas instâncias anteriores do Onyx pelo fluxo normal;
3. reinicie o aplicativo;
4. execute o preflight instalado em PowerShell:

```powershell
& "$env:LOCALAPPDATA\Programs\Cyryx Labs\Onyx\Onyx.exe" --preflight-only
```

### O Onyx não responde por voz

- confirme que o microfone correto está selecionado;
- feche outros aplicativos que possam manter o dispositivo exclusivo;
- verifique rede e credencial Gemini;
- use texto para distinguir falha de áudio de falha geral;
- execute a prontidão por código-fonte:

```powershell
python -m core.readiness --json
```

Provas físicas são opt-in:

```powershell
python -m core.readiness --hardware --json
python -m core.readiness --camera --json
python -m core.readiness --live-api --json
python -m core.readiness --integrated-voice --timeout 30 --json
```

O teste integrado captura áudio temporariamente e o envia ao Gemini Live. Leia
a descrição do comando antes de executá-lo.

### A câmera não acompanha corretamente

- melhore a iluminação frontal;
- remova luz forte atrás do usuário;
- deixe a mão/rosto inteiros dentro do quadro;
- calibre novamente a posição e distância;
- confira a permissão de câmera do Windows;
- feche outro aplicativo que esteja usando a webcam.

### O celular não conecta

- confirme a mesma rede local;
- revise VPN, isolamento de cliente do roteador e firewall;
- gere um novo QR code em **Remote**;
- aceite conscientemente o certificado local daquela instalação;
- não reutilize tickets ou códigos expirados.

### Uma ação foi recusada

A recusa normalmente significa um dos seguintes casos:

- faltou um argumento obrigatório;
- a ação não é reconhecida;
- o alvo é protegido;
- a confirmação foi negada ou expirou;
- a conta/dispositivo/provedor não está configurado;
- a operação não tem um adaptador oficial;
- o resultado anterior ficou incerto e precisa de reconciliação;
- o limite, prazo ou orçamento foi atingido.

Peça: “Explique exatamente qual pré-condição está faltando, sem executar nada.”

## 22. Referência CLI para administradores

Os comandos abaixo são destinados ao checkout autorizado do código-fonte, salvo
quando o executável instalado é indicado explicitamente.

| Área | Comando de descoberta |
|---|---|
| Prontidão | `python -m core.readiness --help` |
| Missões | `python -m core.missions --help` |
| Memória | `python -m memory.memory_manager --help` |
| Áudio | `python scripts/onyx_audio_cli.py --help` |
| Identidade | `python scripts/onyx_identity_cli.py --help` |
| Capacidades | `python scripts/onyx_capabilities_cli.py --help` |
| Paridade | `python scripts/onyx_parity_cli.py --help` |
| Clipboard/wellness | `python scripts/onyx_personal_tools_cli.py --help` |
| Personalização governada | `python scripts/onyx_personalization_cli.py --help` |
| Plugins | `python scripts/onyx_plugin_cli.py --help` |
| Social | `python scripts/onyx_social_cli.py --help` |
| Repetições por visão | `python scripts/onyx_vision_repetition_cli.py --help` |
| Google Workspace | `python scripts/onyx_google_workspace.py --help` |
| Microsoft DayOps instalado | `Onyx-DayOps.exe --help` |

Diagnósticos do executável instalado:

```powershell
& "$env:LOCALAPPDATA\Programs\Cyryx Labs\Onyx\Onyx.exe" --preflight-only
& "$env:LOCALAPPDATA\Programs\Cyryx Labs\Onyx\Onyx.exe" --parity-smoke-v1
& "$env:LOCALAPPDATA\Programs\Cyryx Labs\Onyx\Onyx.exe" --capabilities-smoke-v1
```

## 23. Limites atuais da versão 1.1.20

O pacote local Windows 1.1.20 foi empacotado, instalado e verificado, mas continua
sem assinatura Authenticode. Ele é um candidato local não assinado, não uma
distribuição pública formal confiável.

Permanecem dependentes de prova/ativação externa:

- sessão física completa de voz/Gemini Live;
- calibração real de câmera e mão no ambiente de cada usuário;
- consentimento OAuth e conta para Microsoft Graph e Google Workspace;
- adaptadores oficiais, contas e recibos para publicação social live;
- fontes live governadas para Argos;
- um Network Guardian autônomo separado e certificado para bloquear ataques ou
  alterar firewall automaticamente;
- clientes, sensores e provedores específicos de cada ação;
- certificado Authenticode para distribuição pública formal.

O Onyx deve declarar essas ausências de forma explícita. Uma prévia, teste local,
manifesto ou contrato não equivale a um efeito confirmado em um serviço externo.

## 24. Referências oficiais do projeto

- `docs/onyx/ONYX_FUNCTIONAL_PARITY_V1.md` — paridade funcional e limites de evidência.
- `core/capability_parity_v1.py` — registro fechado das 42 capacidades.
- `docs/onyx/APPROVAL_POLICY.md` — política de autorização.
- `docs/MISSIONS.md` — contrato detalhado de missões.
- `docs/INSTALLATION.md` — instalação e empacotamento.
- `docs/onyx/PHASE8_MICROSOFT_GRAPH_LIVE_ONBOARDING.md` — onboarding Microsoft Graph.
- `docs/onyx/ONYX_DAYOPS_V14.md` — operação DayOps e Microsoft 365.
- `docs/onyx/THREAT_MODEL.md` — modelo de ameaças.

## 25. Suporte e propriedade

Onyx é projetado, desenvolvido e mantido pela **Cyryx Labs LLC**. Não altere
arquivos internos, políticas, evidências ou credenciais para contornar uma
recusa. Registre a mensagem exata, a versão instalada, a operação solicitada e
o estado exibido ao solicitar suporte.

Copyright © 2026 Cyryx Labs LLC. Todos os direitos reservados.
