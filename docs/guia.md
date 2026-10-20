# Como executar

Esta página reúne, em um só lugar, tudo para subir, testar, parar e destruir o ambiente. O texto vem do [README do repositório](https://github.com/lucasetculbra/achados-perdidos-docker-compose#readme).

> NOTE: **Lembrete.** Este site é só a **documentação**. A aplicação roda no seu computador, com Docker; depois do passo 2 ela fica em `http://localhost:8080`.

--8<-- "README.md:passo-a-passo"

## Exemplo completo no PowerShell (Windows)

```powershell
git clone https://github.com/lucasetculbra/achados-perdidos-docker-compose.git
cd achados-perdidos-docker-compose
Copy-Item .env.example .env          # depois troque a senha no .env
docker compose up -d --build
docker compose ps

curl.exe http://localhost:8080/health
curl.exe http://localhost:8080/itens
curl.exe "http://localhost:8080/itens?local=biblio"
curl.exe -F descricao="Oculos de grau" -F local="Bloco B" -F foto=@C:\Users\voce\Pictures\oculos.jpg http://localhost:8080/itens
curl.exe http://localhost:8080/estatisticas
docker compose logs web --tail 20
```

Troque `C:\Users\voce\Pictures\oculos.jpg` por uma imagem que **exista** no seu computador.

--8<-- "README.md:rotas"

--8<-- "README.md:diagnostico"

## Para ir além

- **Como cada comando afeta itens e fotos** (`stop`, `down`, `down -v`…): [Relatório, parte D](RELATORIO.md#d-ciclo-de-vida-dos-volumes).
- **Painel do banco, backup das fotos e proxy:** [Bônus](bonus.md).
- **Testes automatizados e evidências:** [Evidências](evidencias/README.md) e [CI/CD](cicd.md).
