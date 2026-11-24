# Login com Google no desenvolvimento local

O botão **Continuar com Google** usa OAuth 2.0 Authorization Code com PKCE
e OpenID Connect. O Google confirma a identidade; o RhythmMind emite sua
própria credencial de sessão, com o mesmo isolamento de dados do login local.
A senha da conta Google é informada somente na página do Google.

Sem credenciais OAuth configuradas no servidor, o botão fica desabilitado
com a mensagem de indisponibilidade. Cadastro e entrada por senha continuam
disponíveis, com senhas de 6 a 128 caracteres.

## 1. Criar as credenciais do aplicativo

Na sua conta, abra o [Google Cloud Console](https://console.cloud.google.com/):

1. Crie ou selecione um projeto.
2. Abra **Google Auth Platform** (em interfaces anteriores, **APIs e serviços →
   Tela de consentimento OAuth**).
3. Em **Branding**, informe nome do aplicativo e contatos solicitados.
4. Em **Audience**, escolha o público adequado. Para contas pessoais, use
   **External**, mantenha o aplicativo em **Testing** e adicione sua conta em
   **Test users**.
5. Em **Data Access**, use somente os escopos de identificação `openid`,
   `profile` e `email`. Esta integração não acessa Drive, Gmail ou arquivos.
6. Em **Clients**, crie um cliente OAuth do tipo **Web application**.
7. Em **Authorized redirect URIs**, cadastre exatamente:

   ```text
   http://127.0.0.1:8000/api/auth/google/callback
   ```

8. Guarde o **Client ID** e o **Client secret** para configurar o servidor.

O fluxo usa redirecionamento, sem SDK JavaScript do Google. Uma origem
JavaScript autorizada não é necessária para este fluxo. Não é preciso
habilitar as APIs do Drive/Gmail ou configurar faturamento apenas para
autenticar pessoas.

Use o mesmo host, protocolo, porta e caminho no Console e na configuração
local. `localhost` e `127.0.0.1` são endereços diferentes para essa finalidade.
Se escolher `localhost`, atualize também `RHYTHMMIND_GOOGLE_REDIRECT_URI`.
O aplicativo desta etapa continua restrito ao computador local.

## 2. Instalar e configurar no Windows

Na raiz do repositório, pare o servidor anterior com **Ctrl+C** e execute no
PowerShell do VS Code. Os exemplos usam `.venv`, o nome do ambiente da
instalação local de João; se o seu se chamar `.venv-local`, ajuste o caminho.

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:RHYTHMMIND_GOOGLE_CLIENT_ID = "SEU_CLIENT_ID.apps.googleusercontent.com"
$env:RHYTHMMIND_GOOGLE_REDIRECT_URI = "http://127.0.0.1:8000/api/auth/google/callback"
$segredoGoogle = Read-Host "Client secret do aplicativo Google" -AsSecureString
$credencialGoogle = [System.Net.NetworkCredential]::new("", $segredoGoogle)
$env:RHYTHMMIND_GOOGLE_CLIENT_SECRET = $credencialGoogle.Password
Remove-Variable segredoGoogle, credencialGoogle

.\.venv\Scripts\python.exe -B -m api.desenvolvimento --persistente
```

O segredo é solicitado sem aparecer no terminal nem ficar escrito no
comando. As variáveis são herdadas pelo servidor iniciado nesse terminal;
outro terminal não recebe essa configuração automaticamente. Não cole o
segredo em conversas, código, HTML, capturas de tela ou no Git.

Abra **http://127.0.0.1:8000** no Chrome ou Edge e escolha **Continuar com Google**.
Use um navegador normal: o Google pode recusar autenticação em webviews,
incluindo o Simple Browser embutido no VS Code.

## 3. Configurar em Linux/macOS

Na raiz do repositório, usando Bash:

```bash
.venv-local/bin/python -m pip install -r requirements.txt
export RHYTHMMIND_GOOGLE_CLIENT_ID='SEU_CLIENT_ID.apps.googleusercontent.com'
export RHYTHMMIND_GOOGLE_REDIRECT_URI='http://127.0.0.1:8000/api/auth/google/callback'
read -r -s -p 'Client secret do aplicativo Google: ' RHYTHMMIND_GOOGLE_CLIENT_SECRET
export RHYTHMMIND_GOOGLE_CLIENT_SECRET
.venv-local/bin/python -B -m api.desenvolvimento --persistente
```

O servidor lê as variáveis de ambiente. No início local com `api.desenvolvimento`,
se existir um arquivo `.env.local` na raiz do repositório (ignorado pelo `.gitignore`),
variáveis ainda não definidas no terminal são carregadas dele automaticamente;
valores já definidos no terminal têm prioridade. `RHYTHMMIND_GOOGLE_REDIRECT_URI`
pode ser omitida para usar o endereço padrão com `127.0.0.1` mostrado acima.

## Dados entre reinicializações

O parâmetro `--persistente` guarda contas e arquivos pessoais em
`.rhythmmind-local/`, fora do versionamento. Encerrar e iniciar novamente
com esse parâmetro preserva o mesmo UUID de conta, histórico e catálogo.
Os arquivos existentes não são substituídos pelas sementes fictícias.

Sem o parâmetro, `python -m api.desenvolvimento` mantém o comportamento
anterior: dados fictícios em diretório temporário, descartados ao encerrar
normalmente. Uma conta criada nesse modo não é copiada para o persistente.
Não apague `.rhythmmind-local/` se quiser conservar os dados desse modo.

Google e senha são formas separadas de entrada. O sistema identifica a
conta Google pelo identificador estável do provedor, sem juntar contas
automaticamente porque têm nome ou e-mail parecidos. Uma conta Google
não recebe senha fictícia e não herda registros de outras contas.

## Rotas e sessão

| Método e rota | Uso |
| --- | --- |
| `GET /api/auth/google/config` | Informa se o login Google está disponível, sem expor credenciais |
| `GET /api/auth/google/iniciar` | Cria um fluxo temporário e redireciona para o Google |
| `GET /api/auth/google/callback` | Confere o retorno do provedor e prepara a conclusão local |
| `POST /api/auth/google/concluir` | Consome a conclusão de uso único e entrega a credencial local ao frontend |

O fluxo valida `state`, PKCE, `nonce` e o ID token do Google. Cookies
temporários HttpOnly vinculam o início e o retorno ao navegador. A credencial
Bearer do RhythmMind não é incluída na URL e permanece somente na memória
do frontend. `/api/auth/eu` e `/api/auth/sair` continuam identificando a conta
e encerrando a entrada atual.

## Verificação e problemas comuns

- **Botão indisponível:** confira se Client ID e Client secret foram definidos
  no mesmo terminal que iniciou o servidor, depois reinicie o processo.
- **`redirect_uri_mismatch`:** compare a URI cadastrada no Google com a
  variável do servidor, incluindo host, protocolo, porta e caminho.
- **Acesso negado em Testing:** confira se a conta usada está na lista de
  usuários de teste do projeto Google.
- **Recusa em navegador embutido:** abra a URL local no Chrome ou Edge.
- **Fluxo expirado, cancelado ou interrompido:** volte à tela inicial e
  comece novamente. O código de retorno e a conclusão local são de uso único.
- **Histórico vazio depois de reiniciar:** confira se os dois lançamentos
  usaram `--persistente` e se a entrada foi feita pela mesma conta e método.

Os testes automatizados usam identidades fictícias e clientes simulados;
não dependem de uma chave Google nem fazem login em uma conta real. A
validação ponta a ponta com o Google exige credenciais válidas e uma conta
de teste autorizada.

Esta entrega prepara e testa o uso local. Não publica o aplicativo nem
substitui a configuração HTTPS, revisão operacional e requisitos do Google
necessários a uma futura implantação pública.

Referências: [OpenID Connect do Google](https://developers.google.com/identity/openid-connect/openid-connect),
[OAuth 2.0 para aplicações de servidor](https://developers.google.com/identity/protocols/oauth2/web-server),
[políticas OAuth](https://developers.google.com/identity/protocols/oauth2/policies).
