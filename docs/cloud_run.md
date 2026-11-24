# Publicação no Google Cloud Run (Opção 1 — MVP temporário)

Este guia resume o que foi preparado no projeto para publicar o **RhythmMind** no **Google Cloud Run** com armazenamento temporário no container (Opção 1), mantendo o modo de desenvolvimento local bloqueado por padrão.

## O que mudou no código

* [api/producao.py](api/producao.py): inicializador de produção que escuta em `0.0.0.0:$PORT` (padrão `8080`), ativa o modo produção com proxy HTTPS (`proxy_headers=True`, `forwarded_allow_ips="*"`) e separa os dados privados graváveis (`RHYTHMMIND_DIRETORIO_DADOS`, padrão em pasta temporária do container).
* [api/main.py](api/main.py) e [api/autenticacao.py](api/autenticacao.py): mantêm as travas locais por padrão e só liberam tráfego externo quando `modo_producao` está ativo; adicionam `/healthz` fora do esquema OpenAPI.
* [core/google_oidc.py](core/google_oidc.py) e [api/google_auth.py](api/google_auth.py): quando `RHYTHMMIND_AMBIENTE=producao`, exigem `RHYTHMMIND_GOOGLE_REDIRECT_URI` explícito em `https://` com domínio válido e respeitam `X-Forwarded-Proto: https` para cookies `Secure`.
* [Dockerfile](Dockerfile), [.dockerignore](.dockerignore) e [.gcloudignore](.gcloudignore): empacotam a aplicação em Python 3.13 com usuário não-root, excluindo `.env.local`, `.venv/`, dados locais e arquivos de teste.

> [!IMPORTANT]
> Nesta Opção 1, contas (`acesso.sqlite3`) e registros (`data/usuarios/`) ficam na memória temporária do container do Cloud Run: quando a instância hiberna por inatividade ou recebe nova revisão, os registros zeram (e contas Google voltam a entrar com um clique).

## Ordem segura para publicar no Google Cloud Run

1. **Conta de Faturamento no projeto `rhythmmind`**
   * No Google Cloud Console, vincule uma conta de faturamento (como o teste grátis de US$ 300 / *Always Free*) para habilitar Cloud Run e Cloud Build.
   * No teste grátis, o Google informa que não faz cobrança automática após o término dos créditos sem upgrade manual.

2. **Primeiro deploy para obter a URL HTTPS do Cloud Run**
   * Você pode usar o **Cloud Shell** (no próprio navegador dentro do Google Cloud Console) ou a `gcloud` CLI após validar a sintaxe exata com `gcloud help run deploy` e habilitar as APIs necessárias (`run.googleapis.com` e `cloudbuild.googleapis.com`).
   * Suba primeiro **sem** configurar `RHYTHMMIND_GOOGLE_*` (ou deixe para configurar após gerar a URL). O app já entra no ar com login por usuário/senha e gera sua URL fixa `https://<servico>-<id>.run.app`.
   * Recomenda-se limitar a **1 instância máxima** nessa fase de SQLite local em container, para evitar dois containers isolados dividindo sessões enquanto houver uso simultâneo.

3. **Configurar o Login com Google para a URL publicada**
   * No **Google Auth Platform → Clientes**, cadastre `https://<sua-url-cloud-run>/api/auth/google/callback` em **URIs de redirecionamento autorizados** e `https://<sua-url-cloud-run>` em **Origens JavaScript autorizadas** (ou crie um cliente separado para produção).
   * Em **Google Auth Platform → Público-alvo**, mantendo o status em **Testando**, adicione os e-mails Gmail seus e dos seus amigos em **Usuários de teste**.

4. **Definir as variáveis no Cloud Run**
   * `RHYTHMMIND_AMBIENTE=producao`
   * `RHYTHMMIND_GOOGLE_CLIENT_ID=<seu-client-id>`
   * `RHYTHMMIND_GOOGLE_CLIENT_SECRET=<seu-client-secret>` *(preferencialmente via Secret Manager do Google Cloud ou variável de ambiente secreta no serviço)*
   * `RHYTHMMIND_GOOGLE_REDIRECT_URI=https://<sua-url-cloud-run>/api/auth/google/callback`
