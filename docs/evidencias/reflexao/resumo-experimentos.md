# Resumo dos experimentos da reflexão

Gerado em 2026-10-19T22:57:13-03:00 — **20/20 verificações aprovadas**.

| Requisito | Verificação | Resultado |
|---|---|---|
| Q1 | na rede bridge padrão o nome do outro contêiner NÃO é resolvido | ✅ passou |
| Q1 | em rede definida pelo usuário o nome é resolvido para o IP do contêiner | ✅ passou |
| Q1 | o resolvedor da rede definida é o DNS embutido 127.0.0.11 | ✅ passou |
| Q5 | build do zero executa o pip install (sem cache) | ✅ passou |
| Q5 | sem mudanças: pip install e COPY app.py vêm do cache | ✅ passou |
| Q5 | só o app.py mudou: pip install CACHED, COPY app.py refeito | ✅ passou |
| Q5 | requirements.txt mudou: pip install é refeito | ✅ passou |
| Q5 | reconstruir só com o app.py alterado é mais rápido que reinstalar as dependências — só app.py 2.5s x requirements.txt 11.8s (do zero 13.1s, sem mudanças 1.5s) | ✅ passou |
| Q3 | o log do db mostra que a inicialização foi ignorada (Skipping initialization) | ✅ passou |
| Q3 | com o init.sql alterado, a coluna 'contato' NÃO foi criada | ✅ passou |
| Q3 | o ALTER TABLE criou a coluna 'contato' | ✅ passou |
| Q3 | nenhuma linha foi perdida (mesma contagem antes e depois da migração) — 4 linhas antes e 4 depois | ✅ passou |
| Q3 | a aplicação continua funcionando depois da migração (GET /itens) | ✅ passou |
| Q7 | up -d --scale web=3 termina com sucesso (com o nginx e sem porta fixa no web) | ✅ passou |
| Q7 | existem 3 réplicas do web em execução | ✅ passou |
| Q7 | as 3 réplicas atendem requisições (campo 'container' do /health tem 3 valores) — 3 réplicas distintas responderam | ✅ passou |
| Q7 | as 3 réplicas enxergam os mesmos arquivos no volume fotos compartilhado | ✅ passou |
| Q7 | com porta fixa no web, up --scale web=3 falha (conflito de porta no host) | ✅ passou |
| Q7 | depois de remover o override o ambiente volta ao normal com 1 réplica | ✅ passou |
| RNF03 | evidências dos experimentos não contêm a senha do .env nem caminhos do computador do autor | ✅ passou |

Gerado por `scripts/experimentos_reflexao.py`; cada linha é uma asserção executada contra o ambiente real.
