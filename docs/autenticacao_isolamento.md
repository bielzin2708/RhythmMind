# Contas, autenticação e isolamento local

Esta entrega implementa somente backend e lógica. Não cria telas nem muda
a interpretação emocional, a escolha musical ou a semântica do feedback.

## Executar

Na raiz do projeto, em PowerShell:

```powershell
.\.venv-local\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-local\Scripts\python.exe -m pip check
.\.venv-local\Scripts\python.exe -B -m api.desenvolvimento
```

Abra http://127.0.0.1:8000/docs. Use exclusivamente contas, senhas e relatos
fictícios. A API continua escutando somente em 127.0.0.1, sem confiar em
cabeçalhos de proxy. Host/cliente externos são recusados, e requisições fora
da raiz temporária autorizada retornam 503. Não habilite reload, workers,
proxy ou publicação na rede.

O inicializador é descartável: contas, acessos e JSON pessoais ficam em
diretório temporário e são apagados ao encerrar normalmente. Reiniciar esse
inicializador cria outra base fictícia. O armazenamento suporta reabertura
sobre os mesmos arquivos, como verificado nos testes; esse launcher não
oferece persistência entre lançamentos. Encerramento forçado pode deixar
o temporário no disco.

## Rotas de acesso

| Método e rota | Comportamento |
| --- | --- |
| `POST /api/auth/registrar` | Cria conta e retorna perfil; não autentica automaticamente |
| `POST /api/auth/entrar` | Confere senha e emite uma nova credencial de acesso |
| `GET /api/auth/eu` | Retorna somente o perfil da credencial validada |
| `POST /api/auth/sair` | Revoga a credencial atual; retorna 204 |

Cadastro e entrada recebem:

```json
{
  "nome_usuario": "conta_ficticia",
  "senha": "senha-ficticia-de-exemplo-123!"
}
```

Este é apenas um exemplo descartável, não uma conta padrão criada pelo
sistema. O nome admite 3 a 64 letras ASCII, números, ponto, hífen ou
sublinhado e é armazenado em minúsculas; nomes são únicos sem distinguir
maiúsculas. Senhas têm de 12 a 128 caracteres e não são recortadas nem
normalizadas.

O perfil contém `usuario_id` UUID gerado no servidor, `nome_usuario` e
`criado_em` em UTC. Nunca contém senha ou hash.

A entrada retorna `token_acesso`, `tipo_token: "bearer"`, `expires_in: 3600`
e `expira_em` em UTC. Informe somente o valor de `token_acesso` no botão
Authorize do Swagger, ou envie:

```text
Authorization: Bearer <credencial recebida na entrada>
```

A credencial é um segredo de acesso: não a coloque em URL, logs, exemplos
persistidos ou no Git. Não há JWT nem segredo de assinatura estático. Cada
entrada gera outra credencial; sair encerra somente a entrada atual.
Não apaga a conta, o histórico ou as sessões de relato.

A expiração é absoluta: 3.600 segundos desde a emissão, sem extensão por
atividade ou renovação automática. O servidor consulta o estado de acesso
a cada requisição. Credenciais ausentes, inválidas, expiradas ou revogadas
retornam 401 com `WWW-Authenticate: Bearer`. Nome/senha incorretos usam uma
mensagem genérica. Cadastro duplicado retorna 409.

Todas as rotas funcionais em `/api/` exigem autenticação, exceto cadastro e
entrada. Respostas da API usam `Cache-Control: no-store`. Erros de validação
não devolvem o corpo recebido; falhas do banco retornam 503 sem detalhes
internos. Cadastros rejeitam campos extras.

## Decisões e armazenamento

Senhas usam Argon2id com `pwdlib[argon2]` 0.3.1 e `argon2-cffi` 25.1.0,
nos parâmetros recomendados pela biblioteca. Não há implementação própria
de hash de senha. Credenciais opacas usam 32 bytes aleatórios de
`secrets.token_urlsafe`. Somente seu resumo SHA-256 é persistido; o valor
original é entregue uma vez ao cliente.

| Caminho dentro da raiz autorizada | Uso |
| --- | --- |
| `data/acesso.sqlite3` | Contas, hashes de senhas e acessos com expiração/revogação |
| `data/usuarios/<usuario_id>/historico.json` | Sessões e seus relatos, desejo, escolhas, escuta e feedback |
| `data/usuarios/<usuario_id>/musicas_usuario.json` | Catálogo pessoal daquela conta |
| `data/dicionario_emocional.json` | Referência compartilhada, sem registros pessoais |
| `data/historico.json`, `data/musicas_usuario.json` | Arquivos legados sem titular, fora da API de contas |

O SQLite usa transações, parâmetros SQL e chaves estrangeiras. Não contém
relatos nem o conteúdo das músicas. Bancos locais e seus arquivos auxiliares
estão no `.gitignore`, assim como os JSON pessoais.

A associação persistida dos registros ao titular é o namespace de arquivos
com UUID da conta, ligado à identidade existente no SQLite. Os registros
JSON conservam sua forma anterior; não se acrescenta um campo de titular
controlável pelo cliente. Não existe fallback para o histórico ou catálogo
global quando o arquivo pessoal está ausente: a conta começa vazia.

Uma dependência assíncrona central valida a credencial e estabelece um
`ContextVar` para aquela requisição, com restauração garantida. Isso também
alcança os endpoints síncronos executados no pool de threads. Nenhum usuário
altera globalmente `ARQ_*` ou o diretório de trabalho. O resolvedor recusa
caminhos de outro namespace e links pessoais que escapem do destino permitido.

Um `usuario_id` no corpo é recusado pelos schemas, e parâmetros ou
cabeçalhos de titular não determinam o usuário. Conhecer o UUID de uma
sessão não concede autorização. Consulta, retomada, atualização, feedback
e escuta de outro titular retornam o mesmo 404 de um registro inexistente.
Histórico, padrões, cadastro/listagem musical e recomendações usam somente
os arquivos da conta validada.

O recomendador e o núcleo de sessões foram mantidos. A pontuação, a ordem
das sugestões, os UUIDs e a gravação progressiva não são substituídos pela
autenticação. Informação pendente, escolha explícita de nenhuma faixa e
escuta ainda não informada continuam distintas. Feedback permanece ligado
à experiência da sessão, sem se tornar rótulo global da música.

Uma conta nova precisa cadastrar suas próprias faixas fictícias por
`POST /api/musicas` antes de receber recomendações; não herda o catálogo
legado nem músicas de outra conta. Exemplo de corpo:

```json
{
  "nome": "Faixa Pessoal Ficticia",
  "artista": "Artista Inventado",
  "duracao": "3:00",
  "sentimentos_texto": "calmo"
}
```

## Legados e terminal

Nenhum registro sem autoria é atribuído ao primeiro cadastro, a contas
posteriores ou a um suposto usuário padrão. Os arquivos originais não são
movidos, regravados ou usados como semente de contas.

Não há migração automática ou comando de atribuição nesta entrega. Uma
atribuição futura exigirá autoria confirmada, inventário e hashes dos
originais, mapeamento explícito origem/titular, cópia sem modificar UUIDs
e verificação de conteúdo/quantidades, com relatório revisável antes de
aplicar. Na ausência dessa evidência, os legados continuam separados.

O terminal permanece uma ferramenta de desenvolvimento. Para um ambiente
somente fictício e temporário:

```powershell
.\.venv-local\Scripts\python.exe -B desenvolvimento_terminal.py
```

Ele não faz login, não seleciona perfis de contas e não atende os arquivos
pessoais da API. O comando antigo `python main.py` continua como ferramenta
local para o armazenamento legado da pasta atual; não é uma autenticação.
O acesso direto ao sistema de arquivos pelo responsável da máquina fica
fora da fronteira de autorização HTTP.

## Testes

Resultado final em 03/11/2026: **154 testes aprovados** (135 anteriores e 19 novos)
em Python 3.12.6 no Windows; `pip check` sem conflitos. A suíte completa levou
176,662 segundos nesta execução. Uma verificação por AST confirmou os nomes e
as chamadas de verificação dos 135 testes anteriores sem alterações. O terminal
fictício também iniciou e encerrou pela opção 7 com sucesso.

A referência anterior foi executada antes da edição: 135 testes aprovados.
As preparações antigas foram adaptadas para cadastrar/entrar por HTTP real
e sem substituir a dependência de autenticação. Seus dados antigos são
fixtures fictícias atribuídas explicitamente ao namespace de teste;
essa preparação não faz parte do cadastro da aplicação.

Os testes novos usam duas contas fictícias e armazenamento temporário.
Cobrem ausência/invalidade de credencial, Argon2 e ausência de senha/token
original no SQLite, logout individual, expiração inclusive no limite,
reabertura do banco, acesso cruzado por UUID, titular forjado, isolamento
de histórico/padrões/músicas, recomendações e estados progressivos,
requisições simultâneas de contas distintas, legados anteriores à primeira
conta e tratamento de falha do banco sem expor detalhes.

```powershell
.\.venv-local\Scripts\python.exe -m pip check
.\.venv-local\Scripts\python.exe -B -m unittest discover -s tests -v
```

## Limites antes do uso real

Esta é uma base local com dados fictícios, não uma implantação de contas
reais. Permanecem necessários endurecimento operacional, TLS, limitação de
tentativas de entrada, recuperação de conta, políticas de sessão e revisão
de segurança antes de uso real. Não foram implementados recuperação por
email, MFA, administração ou limpeza periódica de acessos expirados.

Os JSON continuam com escrita atômica, mas não constituem uma transação
para múltiplos gravadores simultâneos da mesma conta. Não habilitar
múltiplos workers ou processos. A separação por conta não cifra o disco
nem protege contra quem já tem acesso autorizado aos arquivos do servidor.

Se um pedido já foi autenticado quando outro pedido faz logout, ele pode
concluir; pedidos posteriores com a credencial revogada são recusados.
Não há interface web ou política de armazenamento de tokens no navegador
nesta etapa.

Referências primárias: [FastAPI: senhas e pwdlib/Argon2](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/),
[OWASP: gerenciamento de sessões](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet/).
