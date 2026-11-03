# Versionamento do RhythmMind

Projeto de TCC do IFPR Campus Londrina. A raiz do repositorio e a pasta
que contem main.py, core/, api/, tests/ e requirements-dev.txt.
A copia recebida nesta maquina ja contem UUID, feedback ausente, escuta,
salvamento progressivo e retomada; a implementacao recebida e preservada
no primeiro commit. Nao ha historico Git na copia recebida.

## Conteudo publicado

Codigo, testes, dependencias e documentacao ficam versionados.
O dicionario emocional e musicas_base.json sao referencias originais;
musicas_exemplo.json contem somente faixas inventadas para iniciar um clone.
O catalogo local musicas_usuario.json, o CSV pessoal de importacao, historicos,
ambientes virtuais e segredos ficam ignorados e permanecem no computador.
Nunca adicione esses arquivos com git add -f.

Em um clone novo, o terminal aceita catalogo ausente, mas nao recomendara
faixas ate receber um catalogo. Para usar as referencias ficticias, execute
na raiz, somente se o destino ainda nao existir:

```powershell
if (-not (Test-Path data/musicas_usuario.json)) {
    Copy-Item data/musicas_exemplo.json data/musicas_usuario.json
}
```

Use somente relatos ficticios no desenvolvimento. Para a API, execute
python -m api.desenvolvimento conforme o README: ela usa sua propria base
ficticia temporaria. Esse inicializador apaga a base ao encerrar; a garantia
de retomada depende de conservar o mesmo arquivo JSON. Contas, autenticacao,
autorizacao por registro e isolamento ainda sao obrigatorios antes de uso real.

## Publicacao privada

Destino solicitado: https://github.com/bielzin2708/RhythmMind, branch main.
Confirme a conta com gh api user --jq .login. Antes de criar ou conectar,
inspecione o destino com gh repo view bielzin2708/RhythmMind.
Erro de acesso nao comprova que um repositorio privado nao existe.
Se houver conteudo remoto, revise-o antes de integrar; nao force o push.
Para um destino comprovadamente novo, sem README/licenca gerados no servidor:

```powershell
gh repo create bielzin2708/RhythmMind --private --source . --remote origin
git push -u origin main
```

A criacao e o push so contam como concluidos depois de conferir privacidade,
branch remota e igualdade entre o SHA local e o SHA remoto. Nunca registre
senhas ou tokens na documentacao, no Git ou no chat.

Se o terminal nao estiver disponivel, abra esta raiz no VS Code,
Controle do Codigo-Fonte > Publicar Branch > Publicar no repositorio privado
do GitHub, autentique pelo navegador como bielzin2708 e informe RhythmMind.
Se o repositorio ja existir, inspecione-o antes e configure origin com seu
URL; use Publicar Branch/Sincronizar somente depois de revisar o conteudo.

Mantenha o commit inicial separado de ajustes e verificacoes posteriores.
