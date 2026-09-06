---
task: formatar-datajud
owner: '@legal-chief'
owner_type: agent
atomic_layer: task
Input: Use the inputs and prerequisites documented in this task.
Output: Produce every deliverable documented in this task.
Checklist:
  - '[ ] Execute every documented step.'
  - '[ ] Validate every declared output.'
---

# Task: Formatar DATAJUD

**Task ID:** formatar-datajud
**Versao:** 1.0
**Agente:** datajud-formatter
**Squad:** legal-analyst

## Proposito
Formatar dados processuais conforme DATAJUD schema do CNJ e apresentacao estilo JUSBRASIL.

## Inputs
| Parametro | Tipo | Obrigatorio | Descricao |
|-----------|------|-------------|-----------|
| dados | objeto | Sim | Dados processuais para formatar |

## Etapas
1. Validar campos obrigatorios DATAJUD
2. Mapear dados para campos DATAJUD
3. Gerar card de processo (estilo JUSBRASIL)
4. Gerar timeline de movimentacoes
5. Formatar citacoes padronizadas
6. Criar links entre documentos
7. Exportar YAML (DATAJUD) + MD (JUSBRASIL)

## Output
- **Localizacao:** `output/legal/{processo}/dados-datajud.yaml` + `relatorio-jusbrasil.md`

## Criterios de Conclusao
- [ ] DATAJUD schema validado
- [ ] Relatorio JUSBRASIL gerado
- [ ] Citacoes padronizadas
- [ ] Exportacao completa
