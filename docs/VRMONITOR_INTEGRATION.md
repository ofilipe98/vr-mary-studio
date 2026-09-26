# Integração com VRMonitor

O VRStudio preserva seus providers, logins, conversas, streaming, aprovações e MCP. A integração apenas acrescenta nove ferramentas que consultam o VRMonitor central. Nenhuma conta OpenAI adicional é necessária.

Crie `VRProject/.state/vrmonitor.json`:

```json
{
  "version": 1,
  "enabled": true,
  "base_url": "https://monitor.exemplo:8443",
  "client_id": "10000000-0000-0000-0000-000000000001",
  "session_token": "TOKEN_DE_SESSAO_LOCAL_DO_VRMONITOR",
  "ca_file": "monitor-ca.crt"
}
```

O token é emitido pelo login LOCAL do VRMonitor e não é enviado ao provider. `ca_file` é opcional e relativo a `.state`. URL HTTP, redirects, campos extras, UUID não canônico ou token malformado desabilitam a integração de forma segura. Reinicie o aplicativo após mudar o arquivo.

As ferramentas disponíveis são `get_database_activity`, `get_connections`, `get_active_queries`, `get_long_queries`, `get_locks`, `get_blocking_sessions`, `search_schema`, `get_table_schema` e `run_readonly_query`. Codex as recebe nativamente. Claude Code, OpenCode e Antigravity ACP usam o MCP stdio existente com a mesma allowlist e o ID da conversa.

O cliente, a sessão e o token ficam fora dos argumentos do modelo. Respostas chegam com a classificação `UNTRUSTED_DATA`. O VRMonitor central aplica sessão/MFA, RBAC, client scope, capability, Object Policy, Query Guard, limites e auditoria. O perfil `supervised` pede aprovação para todas as operações; SQL read-only também pede aprovação fora de `full_access`.

Cada chamada respeita o limite individual da ferramenta e a paginação disponível. Não há quota cumulativa interna por chamadas, caracteres, tempo ou tokens no chat; cancelar o turno, substituí-lo ou receber um erro real do provider encerra a operação. A resposta HTTP aceita somente JSON sem compressão e até 1 MiB; não há retry automático.
